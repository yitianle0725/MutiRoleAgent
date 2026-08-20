"""将多集合检索结果整理成受控、可引用的 LLM 上下文。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from langchain_core.documents import Document


@dataclass
class ContextBuildResult:
    text: str
    evidence: list[dict[str, object]]
    duplicate_count: int
    truncated: bool


def build_context(
    documents: Iterable[tuple[str, Document]],
    max_chars: int = 8000,
    min_content_chars: int = 12,
) -> ContextBuildResult:
    """去重、过滤空证据并按字符预算构造带引用编号的上下文。"""
    seen: set[str] = set()
    evidence: list[dict[str, object]] = []
    parts: list[str] = []
    duplicate_count = 0
    used_chars = 0
    truncated = False

    for collection, document in documents:
        content = re.sub(r"\s+", " ", document.page_content or "").strip()
        if len(content) < min_content_chars:
            continue
        key = content.casefold()
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        citation_id = len(evidence) + 1
        source = str(document.metadata.get("source", ""))
        page = document.metadata.get("page")
        header = f"[参考资料{citation_id}] collection={collection} source={source}"
        if page is not None:
            header += f" page={page}"
        remaining = max_chars - used_chars
        if remaining <= len(header) + 8:
            truncated = True
            break
        block = f"{header}\n{content}\n"
        if len(block) > remaining:
            block = f"{header}\n{content[: max(0, remaining - len(header) - 8)]}…\n"
            truncated = True
        parts.append(block)
        used_chars += len(block)
        evidence.append({
            "citation_id": citation_id,
            "collection": collection,
            "source": source,
            "page": page,
            "content_preview": content[:300],
        })
        if truncated:
            break

    return ContextBuildResult("\n".join(parts), evidence, duplicate_count, truncated)
