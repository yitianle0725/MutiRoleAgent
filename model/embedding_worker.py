"""
Embedding Worker 线程池
=======================
ThreadPoolExecutor 并行分块 + 嵌入，提升大批量文档入库速度。

Usage::

    from model.embedding_worker import EmbeddingWorker
    from model.factory import embedding_model

    worker = EmbeddingWorker(embedding_model)
    results = worker.chunk_and_embed(
        long_text, chunk_size=200, chunk_overlap=20
    )
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Sequence

from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.config_handler import chroma_config
from utils.logger_handler import logger


class EmbeddingWorker:
    """后台嵌入工作线程池。

    功能:
      - chunk_and_embed: 先分块再并行嵌入
      - embed_documents: 批量嵌入（利用 provider 自带的 batch 能力）
    """

    def __init__(
        self,
        provider,
        max_workers: int | None = None,
    ):
        """
        Args:
            provider: EmbeddingProvider 实例
            max_workers: 最大线程数 (默认从 chroma.yaml 读取，否则 4)
        """
        self._provider = provider
        self._max_workers = max_workers or chroma_config.get(
            "max_workers", 4
        )
        self._batch_size = chroma_config.get("batch_size", 32)

    def chunk_and_embed(
        self,
        text: str,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> list[list[float]]:
        """分块 + 并行嵌入。

        Args:
            text: 长文本
            chunk_size: 每块最大字符数（默认从 chroma.yaml 读）
            chunk_overlap: 块间重叠字符数

        Returns:
            list[list[float]] — 每个 chunk 的向量
        """
        cs = chunk_size or chroma_config.get("chunk_size", 200)
        co = chunk_overlap or chroma_config.get("chunk_overlap", 20)

        spliter = RecursiveCharacterTextSplitter(
            chunk_size=cs,
            chunk_overlap=co,
            separators=chroma_config.get(
                "separators",
                ["\n\n", "\n", ".", "!", "?", "。", "！", "？", " ", ""],
            ),
            length_function=len,
        )

        chunks = spliter.split_text(text)
        if not chunks:
            return []

        logger.debug(
            f"[EmbeddingWorker] 分块完成: {len(chunks)} chunks "
            f"(chunk_size={cs}, overlap={co})"
        )

        return self.embed_documents(chunks)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文档。

        对于少量文本 (≤ batch_size)，直接单线程调用 provider；
        对于大量文本，分批并行处理。

        Args:
            texts: 待嵌入的文本列表

        Returns:
            list[list[float]] — 每个文本的向量
        """
        if not texts:
            return []

        # 小批量 → 直接调 provider（避免线程开销）
        if len(texts) <= self._batch_size:
            return self._provider.embed_documents(texts)

        # 大批量 → 分批并行
        batches = [
            texts[i : i + self._batch_size]
            for i in range(0, len(texts), self._batch_size)
        ]

        logger.debug(
            f"[EmbeddingWorker] 并行嵌入: {len(texts)} docs → "
            f"{len(batches)} batches ({self._max_workers} workers)"
        )

        # 收集结果，保持原有顺序
        results: dict[int, list[list[float]]] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._embed_batch, batch): idx
                for idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.error(
                        f"[EmbeddingWorker] batch {idx} 嵌入失败: {e}"
                    )
                    results[idx] = []

        # 按顺序拼接
        all_vectors = []
        for idx in sorted(results.keys()):
            all_vectors.extend(results[idx])

        logger.debug(
            f"[EmbeddingWorker] 嵌入完成: {len(all_vectors)} vectors"
        )
        return all_vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """单个 batch 的嵌入调用（在 worker 线程中执行）。"""
        return self._provider.embed_documents(batch)
