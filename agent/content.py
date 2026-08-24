"""统一消息内容块模型。

P0 只定义跨入口可使用的数据结构，不改变现有 LangChain 消息格式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ContentBlockType = Literal["text", "image", "file", "audio", "json"]


@dataclass(slots=True)
class ContentBlock:
    """一段可传输的结构化内容。"""

    type: ContentBlockType
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "data": self.data,
            "metadata": dict(self.metadata),
        }


MessageContent = str | list[ContentBlock]


def text_content(text: str) -> ContentBlock:
    """创建文本内容块。"""

    return ContentBlock(type="text", data=str(text))


def normalize_content(content: MessageContent | None) -> MessageContent:
    """规范化内容，便于 API、日志和前端统一处理。"""

    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return [item for item in content if isinstance(item, ContentBlock)]


def content_to_text(content: MessageContent | None) -> str:
    """提取可见文本；附件不会被误当成回答正文。"""

    normalized = normalize_content(content)
    if isinstance(normalized, str):
        return normalized
    return "\n".join(
        str(item.data)
        for item in normalized
        if item.type == "text" and item.data is not None
    )
