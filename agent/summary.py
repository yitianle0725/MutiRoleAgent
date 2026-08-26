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


def build_session_summary(messages: Sequence[Any], *, max_chars: int = 1200) -> str:
    """Session Summary：只说明当前会话到目前为止发生了什么。"""
    return build_history_summary(messages, max_chars=max_chars)


def build_memory_summary(memories: Sequence[str], *, max_chars: int = 1200) -> str:
    """Memory Summary：压缩多条长期经历后留下的稳定信息，不表示当前会话过程。"""
    parts = ["- " + " ".join(str(item).split())[:240] for item in memories if str(item).strip()]
    return "；".join(parts)[:max_chars]


def should_build_summary(messages: Sequence[Any], *, max_messages: int = 20, max_chars: int = 12000) -> bool:
    """按消息数量或近似字符数判断是否需要刷新摘要。"""
    if len(messages) > max_messages:
        return True
    total = sum(len(str(getattr(item, "content", item))) for item in messages)
    return total > max_chars


def build_agent_summary(
    messages: Sequence[Any],
    *,
    tool_events: Sequence[dict[str, Any]] = (),
    errors: Sequence[str] = (),
    max_chars: int = 2400,
) -> str:
    """生成包含目标、工具结果、错误和未完成状态的确定性摘要。"""
    parts: list[str] = []
    history = build_history_summary(messages, max_chars=max_chars // 2)
    if history:
        parts.append("最近对话:\n" + history)
    if tool_events:
        tool_lines = []
        for event in tool_events[-8:]:
            name = event.get("tool_name", "unknown")
            preview = event.get("result_preview", "")
            tool_lines.append(f"- {name}: {preview}")
        parts.append("工具结果:\n" + "\n".join(tool_lines))
    if errors:
        parts.append("失败原因:\n" + "\n".join(f"- {error}" for error in errors))
    return "\n".join(parts)[:max_chars]
