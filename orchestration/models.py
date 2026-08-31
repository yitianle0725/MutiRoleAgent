"""对话主链使用的稳定领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import BaseMessage

if TYPE_CHECKING:
    from runtime.context import RunContext


ConversationMode = Literal["chat", "work"]


@dataclass(frozen=True, slots=True)
class SessionContext:
    """一次会话不可变的身份和模式绑定。"""

    session_id: str
    user_id: str
    persona_id: str
    persona_name: str
    persona_display_name: str
    mode: ConversationMode
    title: str = ""
    summary: str = ""
    workspace: str | None = None


@dataclass(slots=True)
class PromptLayers:
    """把稳定人格、模式规则和动态记忆明确分层。"""

    stable_system: str
    persona_context: str = ""
    mode_context: str = ""
    user_context: str = ""
    session_context: str = ""

    def render(self) -> str:
        parts = [
            self.stable_system,
            self.persona_context,
            self.mode_context,
            self.user_context,
            self.session_context,
        ]
        return "\n\n---\n\n".join(part.strip() for part in parts if part.strip())


@dataclass(slots=True)
class TurnContext:
    """执行器消费的单轮完整上下文。"""

    session: SessionContext
    history: list[BaseMessage] = field(default_factory=list)
    prompt_layers: PromptLayers | None = None
    run_context: RunContext | None = None
