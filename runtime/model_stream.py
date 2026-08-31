"""LangChain 模型 chunk 到 Runtime 增量的归一化。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage, AIMessageChunk

from .think_filter import ThinkStreamFilter


ModelDeltaType = Literal[
    "text_delta",
    "reasoning_delta",
    "tool_call_start",
    "tool_args_delta",
    "usage",
]


@dataclass(frozen=True, slots=True)
class ModelDelta:
    type: ModelDeltaType
    data: dict[str, Any] = field(default_factory=dict)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") in {None, "text"}:
            parts.append(str(item.get("text", "")))
    return "".join(parts)


class LangChainStreamNormalizer:
    """分离正文、reasoning、工具参数和用量，并重建最终 AIMessage。"""

    def __init__(self) -> None:
        self._aggregate: AIMessageChunk | None = None
        self._think_filter = ThinkStreamFilter("leading-only")
        self._started_tools: set[int] = set()

    def apply(self, chunk: AIMessageChunk) -> list[ModelDelta]:
        self._aggregate = chunk if self._aggregate is None else self._aggregate + chunk
        deltas: list[ModelDelta] = []

        additional = chunk.additional_kwargs if isinstance(chunk.additional_kwargs, dict) else {}
        for key in ("reasoning_content", "reasoning", "thinking"):
            value = additional.get(key)
            if isinstance(value, str) and value:
                deltas.append(ModelDelta("reasoning_delta", {"text": value}))

        visible = self._think_filter.push(_content_text(chunk.content))
        captured = self._think_filter.take_thinking()
        if captured:
            deltas.append(ModelDelta("reasoning_delta", {"text": captured}))
        if visible:
            deltas.append(ModelDelta("text_delta", {"text": visible}))

        for tool_chunk in chunk.tool_call_chunks:
            index = int(tool_chunk.get("index") or 0)
            tool_id = str(tool_chunk.get("id") or "")
            name = str(tool_chunk.get("name") or "")
            if index not in self._started_tools and (tool_id or name):
                self._started_tools.add(index)
                deltas.append(ModelDelta(
                    "tool_call_start",
                    {"index": index, "tool_call_id": tool_id, "tool_name": name},
                ))
            arguments = str(tool_chunk.get("args") or "")
            if arguments:
                deltas.append(ModelDelta(
                    "tool_args_delta",
                    {"index": index, "tool_call_id": tool_id, "delta": arguments},
                ))

        usage = chunk.usage_metadata
        if isinstance(usage, dict) and usage:
            deltas.append(ModelDelta("usage", dict(usage)))
        return deltas

    def finish(self) -> tuple[list[ModelDelta], AIMessage]:
        deltas: list[ModelDelta] = []
        visible = self._think_filter.flush()
        captured = self._think_filter.take_thinking()
        if captured:
            deltas.append(ModelDelta("reasoning_delta", {"text": captured}))
        if visible:
            deltas.append(ModelDelta("text_delta", {"text": visible}))

        aggregate = self._aggregate or AIMessageChunk(content="")
        message = AIMessage(
            content=_content_text(aggregate.content),
            tool_calls=list(aggregate.tool_calls),
            invalid_tool_calls=list(aggregate.invalid_tool_calls),
            additional_kwargs=dict(aggregate.additional_kwargs),
            response_metadata=dict(aggregate.response_metadata),
            usage_metadata=aggregate.usage_metadata,
        )
        return deltas, message
