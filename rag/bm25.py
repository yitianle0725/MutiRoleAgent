"""
中文 BM25 稀疏检索
==================
用 jieba 分词实现 BM25 评分，适用于中文文本的稀疏检索。

参照 TypeScript 昔涟 Agent 中的 @node-rs/jieba + BM25 实现。

公式::

    score(D, Q) = Σ IDF(q_i) * f(q_i, D) * (k1 + 1) / (f(q_i, D) + k1 * (1 - b + b * |D| / avgdl))

其中:
  - k1 = 1.5: 词频饱和参数
  - b = 0.75: 长度归一化参数
  - IDF = log((N - df + 0.5) / (df + 0.5) + 1)

Usage::

    from rag.bm25 import ChineseBM25

    bm25 = ChineseBM25()
    bm25.index(documents)        # 构建索引
    results = bm25.search("崩坏星穹铁道", top_k=10)
    # → [(Document, score), ...]
"""

import math
import os
import pickle
from typing import Sequence

from langchain_core.documents import Document

from utils.logger_handler import logger


class ChineseBM25:
    """用 jieba 分词 + BM25Okapi 实现的稀疏检索器。

    特性:
      - jieba 中文分词（支持自定义词典）
      - BM25 公式（k1=1.5, b=0.75）
      - 索引持久化（pickle）
      - score 归一化到 [0, 1]
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Args:
            k1: 词频饱和参数（默认 1.5）
            b: 长度归一化参数（默认 0.75）
        """
        self._k1 = k1
        self._b = b
        self._documents: list[Document] = []
        self._tokenized: list[list[str]] = []
        self._doc_len: list[int] = []       # 每篇文档的 token 数
        self._avgdl: float = 0.0            # 平均文档长度
        self._df: dict[str, int] = {}       # 文档频率
        self._idf: dict[str, float] = {}    # IDF 值
        self._term_freqs: list[dict[str, int]] = []  # 每篇文档的 TF
        self._built = False

    # ==================== 公开接口 ====================

    @property
    def doc_count(self) -> int:
        """已索引的文档数。"""
        return len(self._documents)

    @property
    def is_built(self) -> bool:
        """索引是否已构建。"""
        return self._built

    def index(self, documents: list[Document]):
        """批量分词并构建 BM25 索引。

        对每个文档用 jieba 分词，然后计算 DF/IDF/TF 统计信息。

        Args:
            documents: 待索引的文档列表
        """
        if not documents:
            logger.warning("[ChineseBM25] index() 收到空文档列表，跳过")
            return

        import jieba

        self._documents = list(documents)
        self._tokenized = []
        self._doc_len = []
        self._df = {}
        self._term_freqs = []

        total_len = 0

        for doc in self._documents:
            # jieba 分词（精确模式）
            tokens = list(jieba.cut(doc.page_content))
            tokens = [t.strip() for t in tokens if t.strip()]
            self._tokenized.append(tokens)
            self._doc_len.append(len(tokens))
            total_len += len(tokens)

            # 统计 TF
            tf: dict[str, int] = {}
            seen: set[str] = set()
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1
                seen.add(token)
            self._term_freqs.append(tf)

            # 统计 DF
            for token in seen:
                self._df[token] = self._df.get(token, 0) + 1

        N = len(self._documents)
        self._avgdl = total_len / N if N > 0 else 0

        # 计算 IDF
        self._idf = {}
        for term, df in self._df.items():
            # Robertson-Sparck Jones IDF 公式
            self._idf[term] = math.log(
                (N - df + 0.5) / (df + 0.5) + 1
            )

        self._built = True
        logger.info(
            f"[ChineseBM25] 索引构建完成: {N} 篇文档, "
            f"vocab={len(self._idf)}, avgdl={self._avgdl:.1f}"
        )

    def search(
        self, query: str, top_k: int = 10
    ) -> list[tuple[Document, float]]:
        """BM25 检索。

        Args:
            query: 查询文本
            top_k: 返回结果数

        Returns:
            [(Document, score), ...]，score 已归一化到 [0, 1]
        """
        if not self._built:
            logger.warning("[ChineseBM25] 索引未构建，返回空结果")
            return []

        import jieba

        # 分词
        query_tokens = list(jieba.cut(query))
        query_tokens = [t.strip() for t in query_tokens if t.strip()]

        # 对每篇文档计算 BM25 分数
        scores: list[float] = []
        for i in range(len(self._documents)):
            score = self._score_one(query_tokens, i)
            scores.append(score)

        # 排序取 top_k
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)

        results = []
        max_score = indexed[0][1] if indexed else 1.0

        for idx, score in indexed[:top_k]:
            if score > 0:
                norm_score = score / max_score if max_score > 0 else 0.0
                results.append((self._documents[idx], norm_score))

        return results

    # ==================== 内部方法 ====================

    def _score_one(self, query_tokens: list[str], doc_idx: int) -> float:
        """计算单篇文档对 query 的 BM25 分数。"""
        score = 0.0
        doc_len = self._doc_len[doc_idx]
        tf = self._term_freqs[doc_idx]
        k1 = self._k1
        b = self._b
        avgdl = self._avgdl

        for token in set(query_tokens):
            if token not in self._idf:
                continue

            idf = self._idf[token]
            f = tf.get(token, 0)
            if f == 0:
                continue

            # BM25 核心公式
            numerator = f * (k1 + 1)
            denominator = f + k1 * (1 - b + b * doc_len / avgdl)
            score += idf * numerator / denominator

        return score

    # ==================== 序列化 ====================

    def save(self, path: str):
        """将索引序列化到磁盘（pickle）。

        Args:
            path: 保存路径（如 ``chroma_db/bm25_faq.pkl``）
        """
        data = {
            "_k1": self._k1,
            "_b": self._b,
            "_documents": self._documents,
            "_tokenized": self._tokenized,
            "_doc_len": self._doc_len,
            "_avgdl": self._avgdl,
            "_df": self._df,
            "_idf": self._idf,
            "_term_freqs": self._term_freqs,
            "_built": self._built,
        }
        with open(path, "wb") as f:
            pickle.dump(data, f)
        logger.debug(
            f"[ChineseBM25] 索引已保存: {path} "
            f"({self.doc_count} docs)"
        )

    @classmethod
    def load(cls, path: str) -> "ChineseBM25":
        """从磁盘加载索引。

        Args:
            path: 索引文件路径

        Returns:
            ChineseBM25 实例

        Raises:
            FileNotFoundError: 索引文件不存在
        """
        with open(path, "rb") as f:
            data = pickle.load(f)

        bm25 = cls(k1=data["_k1"], b=data["_b"])
        bm25._documents = data["_documents"]
        bm25._tokenized = data["_tokenized"]
        bm25._doc_len = data["_doc_len"]
        bm25._avgdl = data["_avgdl"]
        bm25._df = data["_df"]
        bm25._idf = data["_idf"]
        bm25._term_freqs = data["_term_freqs"]
        bm25._built = data["_built"]

        logger.info(
            f"[ChineseBM25] 索引已加载: {path} "
            f"({bm25.doc_count} docs)"
        )
        return bm25
