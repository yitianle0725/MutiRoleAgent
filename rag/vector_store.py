"""
向量存储层（多 Collection 支持 + 混合检索）
============================================
管理 FAQ 知识库、Worldbook 世界观库和 Anime 动漫库三个独立的 ChromaDB collection。

v2 升级:
  - 维度校验 (DimensionGuard): 跨 provider 切换自动检测 mismatch
  - 混合检索 (HybridRetriever): Vector(70%) + BM25(30%) + 可选 Reranker
  - BM25 持久化: chroma_db/bm25_{collection}.pkl

Collection 划分
---------------
- **faq**：产品 FAQ、故障排除、选购指南、维护保养
- **worldbook**：角色背景、世界观设定、剧情 lore
- **anime**：番剧 JSON 数据

两个 collection 共享同一个 embedding 模型和分块配置，
但各自独立存储、独立检索、独立 MD5 去重。
"""

import os

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from model.factory import embedding_model
from model.dimension_guard import DimensionGuard
from utils.config_handler import chroma_config
from utils.file_handler import txt_loader, pdf_loader, json_loader, listdir_with_allowed_type, get_file_md5_hex
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


# ==================== 配置常量 ====================

# 有效的 collection 名称
COLLECTION_FAQ = "faq"
COLLECTION_WORLDBOOK = "worldbook"
COLLECTION_ANIME = "anime"
_ALL_COLLECTIONS = (COLLECTION_FAQ, COLLECTION_WORLDBOOK, COLLECTION_ANIME)

# 共享配置
_PERSIST_DIR = get_abs_path(chroma_config["persist_directory"])
_K = chroma_config["k"]

# BM25 索引持久化目录
_BM25_DIR = _PERSIST_DIR


# ==================== 文本分块器（共享） ====================

def _build_spliter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chroma_config["chunk_size"],
        chunk_overlap=chroma_config["chunk_overlap"],
        separators=chroma_config["separators"],
        length_function=len,
    )


# ==================== MD5 去重辅助 ====================

def _check_md5(md5_store_path: str, md5_hex: str) -> bool:
    """检查 MD5 是否已处理过。"""
    if not os.path.exists(md5_store_path):
        open(md5_store_path, "w", encoding="utf-8").close()
        return False
    with open(md5_store_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip() == md5_hex:
                return True
    return False


def _save_md5(md5_store_path: str, md5_hex: str):
    """记录 MD5 到去重文件。"""
    with open(md5_store_path, "a", encoding="utf-8") as f:
        f.write(md5_hex + "\n")


# ==================== VectorStore ====================

class VectorStore:
    """多 Collection 向量存储管理器。

    每个 collection 独立加载文档、独立检索。
    v2: 支持维度校验 + 混合检索 (Vector + BM25)。
    """

    def __init__(self):
        self._stores: dict[str, Chroma] = {}
        self._bm25_indexes: dict[str, "ChineseBM25"] = {}
        self._spliter = _build_spliter()
        self._dim_guard = DimensionGuard(_PERSIST_DIR)

    # ---- 内部：获取/懒加载 collection ----

    def _get_store(self, collection_name: str) -> Chroma:
        """获取指定 collection 的 Chroma 实例（懒加载 + 缓存 + 维度校验）。"""
        if collection_name not in _ALL_COLLECTIONS:
            raise ValueError(
                f"未知的 collection: {collection_name}，"
                f"可选值: {_ALL_COLLECTIONS}"
            )
        if collection_name not in self._stores:
            # 维度校验（mismatch 时自动清空旧数据）
            if embedding_model.is_available():
                self._dim_guard.check_or_clear(
                    collection_name, embedding_model
                )
            else:
                logger.warning(
                    f"[VectorStore] embedding_model 不可用，"
                    f"跳过维度校验"
                )

            self._stores[collection_name] = Chroma(
                collection_name=collection_name,
                embedding_function=embedding_model,
                persist_directory=_PERSIST_DIR,
            )
        return self._stores[collection_name]

    # ---- BM25 索引管理 ----

    def _get_bm25(self, collection_name: str) -> "ChineseBM25":
        """获取 BM25 索引（懒加载 + 缓存）。

        优先从磁盘加载，无缓存则从 ChromaDB 重建。
        """
        if collection_name in self._bm25_indexes:
            return self._bm25_indexes[collection_name]

        from rag.bm25 import ChineseBM25

        bm25_path = os.path.join(_BM25_DIR, f"bm25_{collection_name}.pkl")

        # 尝试从磁盘加载
        if os.path.exists(bm25_path):
            try:
                bm25 = ChineseBM25.load(bm25_path)
                self._bm25_indexes[collection_name] = bm25
                return bm25
            except Exception as e:
                logger.warning(
                    f"[VectorStore] BM25 索引加载失败: {bm25_path}, {e}"
                )

        # 从 ChromaDB 重建
        bm25 = self._rebuild_bm25(collection_name)
        self._bm25_indexes[collection_name] = bm25
        return bm25

    def _rebuild_bm25(self, collection_name: str) -> "ChineseBM25":
        """从 ChromaDB collection 中读取所有文档，重建 BM25 索引。"""
        from rag.bm25 import ChineseBM25

        bm25 = ChineseBM25()
        bm25_path = os.path.join(_BM25_DIR, f"bm25_{collection_name}.pkl")

        try:
            store = self._get_store(collection_name)
            results = store.get()
            documents = results.get("documents", [])
            metadatas = results.get("metadatas", [])

            if documents:
                langchain_docs = [
                    Document(
                        page_content=text,
                        metadata=meta or {},
                    )
                    for text, meta in zip(documents, metadatas)
                ]
                bm25.index(langchain_docs)
                bm25.save(bm25_path)
                logger.info(
                    f"[VectorStore] BM25 索引已重建: {collection_name} "
                    f"({bm25.doc_count} docs)"
                )
        except Exception as e:
            logger.error(
                f"[VectorStore] BM25 索引重建失败: {collection_name}, {e}"
            )

        return bm25

    # ---- 检索器 ----

    def get_retriever(self, collection_name: str = COLLECTION_FAQ):
        """获取指定 collection 的混合检索器。

        返回 HybridRetriever 实例 (Vector + BM25 + 可选 Reranker)。

        Args:
            collection_name: ``"faq"`` / ``"worldbook"`` / ``"anime"``。
        """
        store = self._get_store(collection_name)
        bm25 = self._get_bm25(collection_name)

        from rag.hybrid_retriever import HybridRetriever
        return HybridRetriever(collection_name, store, bm25)

    def get_all_retrievers(self) -> dict[str, object]:
        """获取所有 collection 的检索器。"""
        return {
            name: self.get_retriever(name)
            for name in _ALL_COLLECTIONS
        }

    # ---- 兼容旧接口 (retriever.invoke) ----

    def get_simple_retriever(self, collection_name: str = COLLECTION_FAQ):
        """获取简单的 ChromaDB 检索器（无 BM25/Reranker）。

        向后兼容接口：返回一个可 invoke(query) 的对象。
        """
        store = self._get_store(collection_name)
        return store.as_retriever(search_kwargs={"k": _K})

    # ---- 文档加载 ----

    def load_document(self, collection_name: str | None = None):
        """从配置的 data_path 加载文档到指定 collection。

        Args:
            collection_name: ``"faq"`` / ``"worldbook"`` / ``"anime"`` / ``None``（全部）。
        """
        collections_to_load: list[str] = (
            list(_ALL_COLLECTIONS) if collection_name is None
            else [collection_name]
        )

        for coll_name in collections_to_load:
            if coll_name not in chroma_config:
                logger.warning(f"[VectorStore] collection '{coll_name}' 无配置，跳过")
                continue

            coll_cfg = chroma_config[coll_name]
            data_path = get_abs_path(coll_cfg["data_path"])
            md5_path = get_abs_path(coll_cfg["md5_hex_store"])
            allowed_types = tuple(coll_cfg["allow_knowledge_file_type"])

            if not os.path.exists(data_path):
                os.makedirs(data_path, exist_ok=True)
                logger.info(f"[VectorStore] 创建目录: {data_path}")

            store = self._get_store(coll_name)
            new_docs_count = self._load_files(store, data_path, md5_path, allowed_types)

            # 有新文档 → 重建 BM25 索引
            if new_docs_count > 0:
                bm25 = self._rebuild_bm25(coll_name)
                self._bm25_indexes[coll_name] = bm25

    def _load_files(
        self,
        store: Chroma,
        data_path: str,
        md5_path: str,
        allowed_types: tuple[str, ...],
    ) -> int:
        """加载单个目录下的所有文件到指定 store。

        Returns:
            成功加载的文件数（用于判断是否需要重建 BM25）。
        """
        allowed_files = listdir_with_allowed_type(data_path, allowed_types)

        if not allowed_files:
            logger.info(f"[VectorStore] {data_path} 无待加载文件")
            return 0

        loaded_count = 0

        for path in allowed_files:
            md5_hex = get_file_md5_hex(path)

            if _check_md5(md5_path, md5_hex):
                logger.debug(f"[VectorStore] {path} 已存在，跳过")
                continue

            try:
                documents = self._load_file_documents(path)
                if not documents:
                    logger.warning(f"[VectorStore] {path} 无有效文本，跳过")
                    continue

                split_docs = self._spliter.split_documents(documents)
                if not split_docs:
                    logger.warning(f"[VectorStore] {path} 分片后为空，跳过")
                    continue

                store.add_documents(split_docs)
                _save_md5(md5_path, md5_hex)
                loaded_count += 1
                logger.info(
                    f"[VectorStore] {path} → {store._collection_name} "
                    f"({len(split_docs)} chunks)"
                )

            except Exception as e:
                logger.error(f"[VectorStore] {path} 加载失败: {e}", exc_info=e)
                continue

        return loaded_count

    @staticmethod
    def _load_file_documents(path: str) -> list[Document]:
        """根据文件扩展名选择合适的加载器。

        支持: txt / pdf / json。
        JSON 文件使用 json_loader，将整个 JSON 作为文本块加载。
        """
        if path.endswith(".txt"):
            return txt_loader(path)
        if path.endswith(".pdf"):
            return pdf_loader(path)
        if path.endswith(".json"):
            return json_loader(path)
        return []

    # ---- 一次性加载全部 ----

    def load_all(self):
        """加载所有 collection 的文档。"""
        self.load_document(collection_name=None)


# ==================== 模块级单例 ====================

vector_store = VectorStore()
