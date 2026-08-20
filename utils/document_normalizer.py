"""知识库文档的统一规范化。

Loader 负责读取不同文件格式；本模块只负责把读取结果整理成稳定、可追溯的
LangChain Document，供向量化和 BM25 共用。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from pathlib import Path

from langchain_core.documents import Document


def normalize_documents(
    documents: Sequence[Document],
    source_path: str,
) -> list[Document]:
    """清理正文并补齐可追溯元数据，丢弃空文档和同页重复正文。"""
    normalized_source = str(Path(source_path).resolve())
    seen_contents: set[str] = set()
    results: list[Document] = []

    for index, document in enumerate(documents, start=1):
        content = normalize_text(document.page_content)
        if not content or content in seen_contents:
            continue

        metadata = dict(document.metadata)
        metadata["source"] = normalized_source
        metadata.setdefault("source_name", Path(source_path).name)
        metadata.setdefault("document_index", index)
        metadata.setdefault("page", metadata.get("page", index - 1))
        results.append(Document(page_content=content, metadata=metadata))
        seen_contents.add(content)

    return results


def normalize_text(text: str) -> str:
    """执行低风险文本清洗，不改写原始语义。"""
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    # PDF 常见的单换行断句：仅在两侧均非明显段落边界时合并。
    value = re.sub(r"(?<![。！？.!?;；:：])\n(?!\n|[-*#])", " ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()
