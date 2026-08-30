"""对话编排层的惰性导出，避免领域模型导入时触发完整运行时。"""

from __future__ import annotations


__all__ = ["AgentRun", "ConversationCoordinator", "RoleplayEngine", "RunStore", "SessionAgentRunner"]


def __getattr__(name: str):
    if name == "ConversationCoordinator":
        from .coordinator import ConversationCoordinator
        return ConversationCoordinator
    if name == "RoleplayEngine":
        from .roleplay import RoleplayEngine
        return RoleplayEngine
    if name in {"AgentRun", "RunStore"}:
        from .runs import AgentRun, RunStore
        return {"AgentRun": AgentRun, "RunStore": RunStore}[name]
    if name == "SessionAgentRunner":
        from .session_runner import SessionAgentRunner
        return SessionAgentRunner
    raise AttributeError(name)
