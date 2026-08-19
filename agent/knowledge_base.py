"""
知识库（用户上传路径）
======================
处理 Streamlit 侧边栏用户上传的文件，写入 FAQ 知识库。

v2: 增加维度校验 + BM25 索引同步。
"""

import os
import hashlib
import sqlite3
from datetime import datetime

from langchain_chroma import Chroma
from model.factory import embedding_model
from model.dimension_guard import DimensionGuard
from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.config_handler import chroma_config
from utils.path_tool import get_abs_path
from utils.logger_handler import logger


def get_string2md5(input_str: str, encoding='utf-8'):
    str2bytes = input_str.encode(encoding=encoding)
    return hashlib.md5(str2bytes).hexdigest()


class KnowledgeBaseService(object):
    def __init__(self):
        # 用户上传走 faq 知识库
        faq_config = chroma_config["faq"]
        persist_dir = get_abs_path(chroma_config["persist_directory"])
        os.makedirs(persist_dir, exist_ok=True)

        # 维度校验（mismatch 时自动清空旧数据）
        self._dim_guard = DimensionGuard(persist_dir)
        if embedding_model.is_available():
            self._dim_guard.check_or_clear(
                faq_config["collection_name"], embedding_model
            )
        else:
            logger.warning(
                "[KB] embedding_model 不可用，跳过维度校验"
            )

        self.chroma = Chroma(
            collection_name=faq_config["collection_name"],
            embedding_function=embedding_model,
            persist_directory=persist_dir,
        )

        # max_split_char_number 不在 chroma.yaml 中，取与 chunk_size 一致
        self.max_split_char_number = faq_config.get(
            "max_split_char_number", chroma_config["chunk_size"]
        )

        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_config["chunk_size"],
            chunk_overlap=chroma_config["chunk_overlap"],
            separators=chroma_config["separators"],
            length_function=len,
        )

        # MD5 去重路径
        self._file_index_path = get_abs_path("db/knowledge_files.sqlite3")
        os.makedirs(os.path.dirname(self._file_index_path), exist_ok=True)
        with sqlite3.connect(self._file_index_path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_files (
                    file_path TEXT NOT NULL,
                    collection_name TEXT NOT NULL,
                    last_modified_ts INTEGER NOT NULL,
                    md5_hex TEXT NOT NULL,
                    PRIMARY KEY (file_path, collection_name)
                )
            """)

        # BM25 索引路径
        self._bm25_dir = persist_dir

    def _check_md5(self, md5_str: str) -> bool:
        return False

    def _save_md5(self, md5_str: str):
        return None

    def _sync_bm25(self):
        """上传文档后同步 BM25 索引。"""
        try:
            from rag.bm25 import ChineseBM25

            bm25_path = os.path.join(self._bm25_dir, "bm25_faq.pkl")

            # 读取 ChromaDB 中的所有文档
            results = self.chroma.get()
            documents = results.get("documents", [])
            metadatas = results.get("metadatas", [])

            if documents:
                from langchain_core.documents import Document
                docs = [
                    Document(page_content=text, metadata=meta or {})
                    for text, meta in zip(documents, metadatas)
                ]
                bm25 = ChineseBM25()
                bm25.index(docs)
                bm25.save(bm25_path)
                logger.info(
                    f"[KB] BM25 索引已同步: faq ({bm25.doc_count} docs)"
                )
            # 同步到全局 vector_store 的 BM25 缓存
            from rag.vector_store import vector_store
            vector_store._bm25_indexes.pop("faq", None)
        except Exception as e:
            logger.warning(f"[KB] BM25 索引同步失败: {e}")

    def upload_by_str(self, data: str, filename, file_path: str | None = None):
        md5_hex = get_string2md5(data)
        source_path = os.path.normcase(os.path.abspath(file_path or filename))
        mtime_ns = os.stat(file_path).st_mtime_ns if file_path and os.path.exists(file_path) else 0
        with sqlite3.connect(self._file_index_path) as connection:
            record = connection.execute(
                "SELECT last_modified_ts, md5_hex FROM knowledge_files WHERE file_path = ? AND collection_name = 'faq'",
                (source_path,),
            ).fetchone()
        if record and (record[0] == mtime_ns or record[1] == md5_hex):
            return "[跳过]内容已存在知识库中"
        if self._check_md5(md5_hex):
            logger.info(f"[KB] {filename} 已存在，跳过")
            return "[跳过]内容已存在知识库中"

        try:
            if len(data) > self.max_split_char_number:
                knowledge_chunks: list[str] = self.spliter.split_text(data)
            else:
                knowledge_chunks = [data]

            if record:
                self.chroma.delete(where={"source": source_path})
            metadata = {
                "source": source_path,
                "display_name": filename,
                "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "operator": "ytl"
            }
            self.chroma.add_texts(
                knowledge_chunks,
                metadatas=[metadata for _ in knowledge_chunks],
            )

            with sqlite3.connect(self._file_index_path) as connection:
                connection.execute(
                    """
                    INSERT INTO knowledge_files(file_path, collection_name, last_modified_ts, md5_hex)
                    VALUES (?, 'faq', ?, ?)
                    ON CONFLICT(file_path, collection_name) DO UPDATE SET
                        last_modified_ts = excluded.last_modified_ts,
                        md5_hex = excluded.md5_hex
                    """,
                    (source_path, mtime_ns, md5_hex),
                )
            logger.info(f"[KB] {filename} 上传成功 ({len(knowledge_chunks)} chunks)")

            # 同步 BM25 索引
            self._sync_bm25()

            return "[成功]内容已经成功载入向量库"
        except Exception as e:
            logger.error(f"[KB] {filename} 上传失败: {e}", exc_info=True)
            return f"[失败]上传出错: {str(e)[:100]}"


if __name__ == '__main__':
    service = KnowledgeBaseService()
    r = service.upload_by_str("黑马", "testfile")
    print(r)
