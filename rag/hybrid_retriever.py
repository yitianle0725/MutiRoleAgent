"""
混合检索器
==========
Vector (ChromaDB HNSW 余弦) + BM25 (jieba 稀疏) + 可选 Reranker 重排。

参照 TypeScript 昔涟 Agent 的检索架构:
  - Dense (70%): ChromaDB 向量余弦相似度
  - Sparse (30%): BM25 jieba 分词
  - Reranker (可选): bge-reranker-base 交叉编码器

融合方式: RRF (Reciprocal Rank Fusion) 后加权

Usage::

    from rag.hybrid_retriever import HybridRetriever
    from rag.bm25 import ChineseBM25

    bm25 = ChineseBM25()
    bm25.index(all_docs)

    retriever = HybridRetriever("faq", chroma_store, bm25, config)
    docs = retriever.retrieve("昔涟是谁？", top_k=5)
"""

import os
from typing import Sequence

from langchain_core.documents import Document
from langchain_chroma import Chroma

from utils.config_handler import chroma_config
from utils.logger_handler import logger


# ==================== 配置常量 ====================

_DENSE_WEIGHT = chroma_config.get("retrieval", {}).get("dense_weight", 0.7)
_SPARSE_WEIGHT = chroma_config.get("retrieval", {}).get("sparse_weight", 0.3)
_RERANKER_ENABLED = chroma_config.get("retrieval", {}).get("reranker_enabled", False)
_RERANKER_TOP_K = chroma_config.get("retrieval", {}).get("reranker_top_k", 10)
_RERANKER_FINAL_K = chroma_config.get("retrieval", {}).get("reranker_final_k", 5)
_RERANKER_MODEL = chroma_config.get("retrieval", {}).get("reranker_model", "BAAI/bge-reranker-base")


class HybridRetriever:
    """向量 + BM25 混合检索器。

    LangChain 兼容接口: 可直接用于 LangChain 的检索链。

    检索流程:
        1. Vector search: ChromaDB.similarity_search_with_score → top_k*2
        2. BM25 search: 自有 BM25 索引 → top_k*2
        3. Score merge: weighted sum (dense*0.7 + sparse*0.3)
        4. Re-rank (可选): bge-reranker-base cross-encoder
        5. Return top_k

    所有方法包裹 try-except，单个子检索失败不影响整体。
    """

    def __init__(
        self,
        collection_name: str,
        chroma_store: Chroma,
        bm25_index,
        config: dict | None = None,
    ):
        """
        Args:
            collection_name: Collection 名 (faq/worldbook/anime)
            chroma_store: ChromaDB 实例
            bm25_index: ChineseBM25 实例（已构建索引）
            config: 检索参数覆盖（可选）
        """
        self._collection = collection_name
        self._chroma = chroma_store
        self._bm25 = bm25_index

        cfg = config or {}
        self._dense_w = cfg.get("dense_weight", _DENSE_WEIGHT)
        self._sparse_w = cfg.get("sparse_weight", _SPARSE_WEIGHT)
        self._reranker_enabled = cfg.get("reranker_enabled", _RERANKER_ENABLED)
        self._reranker_top_k = cfg.get("reranker_top_k", _RERANKER_TOP_K)
        self._reranker_final_k = cfg.get("reranker_final_k", _RERANKER_FINAL_K)
        self._reranker_model = cfg.get("reranker_model", _RERANKER_MODEL)

        self._reranker = None  # 懒加载
        self.last_trace: dict[str, object] = {}

    # ==================== LangChain 兼容接口 ====================

    def invoke(
        self, input: str, config: dict | None = None, **kwargs
    ) -> list[Document]:
        """LangChain BaseRetriever 兼容接口。

        供 ``retriever.invoke(query)`` 调用。
        """
        top_k = kwargs.get("k") or (config or {}).get("k", None)
        return self.retrieve(input, top_k=top_k)

    # ==================== 主入口 ====================

    def retrieve(
        self, query: str, top_k: int | None = None
    ) -> list[Document]:
        """混合检索主入口。

        Args:
            query: 查询文本
            top_k: 返回文档数（默认从 chroma.yaml 读取 k=3）

        Returns:
            list[Document] — 按相关度排序的文档列表
        """
        k = top_k or chroma_config.get("k", 3)
        candidate_k = max(k * 3, 10)  # 候选池大小

        # Step 1: Dense vector search
        dense_results = self._vector_search(query, candidate_k)

        # Step 2: Sparse BM25 search
        sparse_results = self._bm25_search(query, candidate_k)

        # Step 3: Merge scores
        merged = self._merge_scores(
            dense_results, sparse_results, query
        )

        # Step 4: Re-rank (optional)
        if self._reranker_enabled and self._is_reranker_available():
            logger.debug(
                f"[HybridRetriever:{self._collection}] "
                f"Reranker 重排 {len(merged)} → {self._reranker_final_k}"
            )
            merged = self._rerank(query, merged[: self._reranker_top_k])

        # Step 5: Return top_k
        final_results = merged[:k]
        self.last_trace = {
            "collection": self._collection,
            "query": query,
            "candidate_k": candidate_k,
            "dense": self._serialize_results(dense_results),
            "sparse": self._serialize_results(sparse_results),
            "final": self._serialize_results(final_results),
            "reranker_enabled": self._reranker_enabled,
            "dense_weight": self._weights_for_query(query)[0],
            "sparse_weight": self._weights_for_query(query)[1],
        }
        return [doc for doc, _ in final_results]

    @staticmethod
    def _serialize_results(
        results: list[tuple[Document, float]],
    ) -> list[dict[str, object]]:
        """保留评测需要的原始排名，同时限制正文长度避免追踪库膨胀。"""
        return [
            {
                "rank": index,
                "score": round(float(score), 6),
                "source": str(document.metadata.get("source", "")),
                "page": document.metadata.get("page"),
                "content": document.page_content[:800],
            }
            for index, (document, score) in enumerate(results, start=1)
        ]

    # ==================== Dense Search ====================

    def _vector_search(
        self, query: str, k: int
    ) -> list[tuple[Document, float]]:
        """ChromaDB 向量检索（余弦相似度）。"""
        try:
            results = self._chroma.similarity_search_with_score(
                query, k=k
            )
            logger.debug(
                f"[HybridRetriever:{self._collection}] "
                f"向量检索: {len(results)} 条"
            )
            return results
        except Exception as e:
            logger.warning(
                f"[HybridRetriever:{self._collection}] "
                f"向量检索失败: {e}"
            )
            return []

    # ==================== Sparse Search ====================

    def _bm25_search(
        self, query: str, k: int
    ) -> list[tuple[Document, float]]:
        """BM25 稀疏检索。"""
        try:
            if not self._bm25 or not self._bm25.is_built:
                return []
            results = self._bm25.search(query, top_k=k)
            logger.debug(
                f"[HybridRetriever:{self._collection}] "
                f"BM25 检索: {len(results)} 条"
            )
            return results
        except Exception as e:
            logger.warning(
                f"[HybridRetriever:{self._collection}] "
                f"BM25 检索失败: {e}"
            )
            return []

    # ==================== Score Fusion ====================

    def _merge_scores(
        self,
        dense: list[tuple[Document, float]],
        sparse: list[tuple[Document, float]],
        query: str = "",
    ) -> list[tuple[Document, float]]:
        """加权融合 Dense + Sparse 分数。

        使用加权和:
          final_score = dense_score * w_dense + sparse_score * w_sparse

        分数均归一化到 [0, 1]。
        """
        # 仅其中之一有结果 → 直接返回
        dense_weight, sparse_weight = self._weights_for_query(query)
        if not sparse:
            return self._normalize_dense(dense)
        if not dense:
            return list(sparse)

        # 构建文档 ID → 加权分映射
        # 用 page_content + metadata source 作为 key
        score_map: dict[str, tuple[Document, float]] = {}

        # Dense 分数归一化
        raw_similarities = [1.0 / (1.0 + max(0.0, s)) for _, s in dense]
        max_similarity = max(raw_similarities, default=1.0)
        for (doc, s), raw_similarity in zip(dense, raw_similarities):
            key = self._doc_key(doc)
            # ChromaDB 返回的是 distance，越小越相关；转为相似度
            # similarity = 1 / (1 + distance)
            sim = raw_similarity / max_similarity if max_similarity else 0.0
            score_map[key] = (doc, sim * dense_weight)

        # Sparse 分数已经归一化 [0,1]
        for doc, s in sparse:
            key = self._doc_key(doc)
            if key in score_map:
                existing_doc, existing_score = score_map[key]
                score_map[key] = (
                    existing_doc,
                    existing_score + s * sparse_weight,
                )
            else:
                score_map[key] = (doc, s * sparse_weight)

        # 排序
        merged = sorted(
            score_map.values(), key=lambda x: x[1], reverse=True
        )
        return merged

    def _weights_for_query(self, query: str) -> tuple[float, float]:
        """精确实体、型号和英文词查询提高 BM25 权重。"""
        import re

        exact_signal = bool(re.search(r"[A-Za-z]{2,}|\d{2,}|[A-Z][A-Za-z0-9_-]+", query))
        if exact_signal:
            sparse = min(0.6, max(self._sparse_w, 0.5))
            return 1.0 - sparse, sparse
        total = self._dense_w + self._sparse_w
        return (self._dense_w / total, self._sparse_w / total) if total else (0.7, 0.3)

    @staticmethod
    def _normalize_dense(
        results: list[tuple[Document, float]],
    ) -> list[tuple[Document, float]]:
        """将 ChromaDB distance 转为相似度并归一化。"""
        if not results:
            return []
        similarities = [1.0 / (1.0 + max(0.0, dist)) for _, dist in results]
        max_similarity = max(similarities, default=1.0)
        out = []
        for (doc, _), similarity in zip(results, similarities):
            out.append((doc, similarity / max_similarity if max_similarity else 0.0))
        return out

    @staticmethod
    def _doc_key(doc: Document) -> str:
        """生成文档唯一标识 key。

        优先用 page_content 的 MD5 + source，确保同内容不同来源的文档可以合并。
        """
        import hashlib

        content_hash = hashlib.md5(
            doc.page_content.encode("utf-8")
        ).hexdigest()[:16]
        source = doc.metadata.get("source", "")
        return f"{content_hash}:{source}"

    # ==================== Reranker ====================

    def _is_reranker_available(self) -> bool:
        """检测 reranker 是否可用（模型已下载/已加载）。"""
        try:
            if self._reranker is not None:
                return True
            # 尝试加载
            self._reranker = _load_reranker()
            return self._reranker is not None
        except Exception as e:
            logger.debug(f"[HybridRetriever] Reranker 不可用: {e}")
            return False

    def _rerank(
        self, query: str, candidates: list[tuple[Document, float]]
    ) -> list[tuple[Document, float]]:
        """用 bge-reranker-base 对候选文档重排序。"""
        if not candidates or self._reranker is None:
            return candidates

        docs = [doc for doc, _ in candidates]
        pairs = [[query, doc.page_content[:512]] for doc in docs]

        try:
            scores = self._reranker.compute_score(pairs)
            if scores is None:
                logger.warning("[HybridRetriever] Reranker 返回空分数")
                return candidates

            # 排序
            reranked = list(zip(docs, scores))
            reranked.sort(key=lambda x: x[1], reverse=True)

            # 取 final_k
            return reranked[: self._reranker_final_k]
        except Exception as e:
            logger.warning(f"[HybridRetriever] Reranker 失败: {e}")
            return candidates


# ==================== Reranker 加载 ====================

class _RerankerWrapper:
    """bge-reranker-base 交叉编码器包装器。

    使用 sentence-transformers 的 CrossEncoder。
    懒加载以节省启动时间和内存（模型约 1.1GB）。
    """

    def __init__(self):
        self._model = None

    def compute_score(self, pairs: list[list[str]]) -> list[float] | None:
        """对 (query, doc) 对计算相关度分数。

        Args:
            pairs: [[query, doc_text], ...]

        Returns:
            list[float] — 每对的相关度分数（越高越相关）
        """
        if self._model is None:
            from sentence_transformers import CrossEncoder

            model_name = self._reranker_model
            logger.info(f"[Reranker] 加载 {model_name}...")
            self._model = CrossEncoder(
                model_name,
                max_length=512,
            )
            logger.info("[Reranker] 加载完成")

        return self._model.predict(pairs).tolist()  # type: ignore[union-attr]


_reranker_instance: _RerankerWrapper | None = None


def _load_reranker() -> _RerankerWrapper | None:
    """全局单例 reranker 加载器。"""
    global _reranker_instance
    if _reranker_instance is not None:
        return _reranker_instance

    try:
        _reranker_instance = _RerankerWrapper()
        return _reranker_instance
    except ImportError:
        logger.warning(
            "[Reranker] sentence-transformers 未安装，"
            "reranker 不可用。安装: pip install sentence-transformers"
        )
        return None
    except Exception as e:
        logger.warning(f"[Reranker] 加载失败: {e}")
        return None
