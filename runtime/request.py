"""与具体 Agent 框架无关的 Runtime 请求。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeRequest:
    """进入 Runtime 的单轮请求，不暴露 LangChain 或 LangGraph 类型。"""

    session_id: str
    prompt: str
    user_id: str | None = None
    persona: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    max_rounds: int = 20
    timeout_seconds: float = 90.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.session_id = str(self.session_id or "default")
        self.prompt = str(self.prompt or "").strip()
        self.max_rounds = max(int(self.max_rounds), 1)
        self.timeout_seconds = max(float(self.timeout_seconds), 1.0)
