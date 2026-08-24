"""统一 Agent 请求 DTO。

入口层只负责把协议请求转换为本对象，后续 Coordinator/Runner 直接消费它。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import BaseMessage

from .content import MessageContent


RouteMode = Literal["auto", "chat_only", "force_agent"]


@dataclass(slots=True)
class AgentRequest:
    session_id: str
    prompt: str
    history: list[BaseMessage] = field(default_factory=list)
    user_id: str | None = None
    persona: str | None = None
    image_urls: list[str | dict[str, Any]] = field(default_factory=list)
    file_attachments: list[str | dict[str, Any]] = field(default_factory=list)
    route_mode: RouteMode = "auto"
    thread_id: str | None = None
    run_id: str | None = None
    max_steps: int = 20
    timeout_seconds: float = 90.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.session_id = str(self.session_id or "default")
        self.prompt = str(self.prompt or "").strip()
        self.thread_id = self.thread_id or self.session_id
        self.max_steps = max(int(self.max_steps), 1)
        self.timeout_seconds = max(float(self.timeout_seconds), 1.0)

    @property
    def content(self) -> MessageContent:
        """返回当前请求的文本内容；附件由专用字段保留。"""

        return self.prompt
