"""Agent 事实结果和统一运行结果。

Agent 层只产生事实和执行信息，角色层可以在后续阶段负责表达包装。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .content import ContentBlock, MessageContent, normalize_content


AgentRunStatus = Literal[
    "completed",
    "failed",
    "cancelled",
    "waiting_for_input",
]


@dataclass(slots=True)
class AgentFactResult:
    """Agent 执行事实，不包含角色语气。"""

    status: AgentRunStatus
    text: str = ""
    content: MessageContent = ""
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    usage: dict[str, int | float] = field(default_factory=dict)
    pending_user_input: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.content = normalize_content(self.content)

    @property
    def ok(self) -> bool:
        return self.status == "completed" and not self.errors

    def add_error(self, message: str) -> None:
        """记录工具或执行错误，并同步调整状态。"""

        cleaned = str(message or "").strip()
        if cleaned and cleaned not in self.errors:
            self.errors.append(cleaned)
        if self.status == "completed":
            self.status = "failed"


@dataclass(slots=True)
class OrchestratedTurnResult:
    """入口统一使用的单轮结果 DTO。"""

    response_text: str = ""
    delegated: bool = False
    completed: bool = True
    run_id: str | None = None
    status: AgentRunStatus | str = "completed"
    steps: int = 0
    role_name: str | None = None
    fact_result: AgentFactResult | None = None
    content_blocks: list[ContentBlock] = field(default_factory=list)
