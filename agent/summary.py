"""Agent 历史摘要策略（P3 基线）。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_history_summary(messages: Sequence[Any], *, max_chars: int = 1200) -> str:
    """生成不调用模型的安全摘要，保留最近消息事实片段。

    P3 先提供确定性摘要；后续可替换为 LangGraph 摘要节点，但状态字段保持不变。
    """

    snippets: list[str] = []
    for message in messages[-8:]:
        content = getattr(message, "content", message)
        if isinstance(content, list):
            content = " ".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        text = " ".join(str(content).split())
        if text:
            snippets.append(text[:240])
    summary = "\n".join(f"- {item}" for item in snippets)
    return summary[:max_chars]
