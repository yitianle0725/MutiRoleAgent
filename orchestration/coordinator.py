"""统一对话编排边界。

P1 版本只做入口收敛和生命周期编排，Agent 业务仍由现有 LangGraph-backed
ReactAgent 执行。P2 再接入独立 RoleplayEngine 和事实结果包装。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent.results import OrchestratedTurnResult
from agent.stream_events import StructuredData, TextChunk, ToolEvent

from .session_runner import SessionAgentRunner


StreamEvent = TextChunk | ToolEvent | StructuredData
CompletionCallback = Callable[[OrchestratedTurnResult], Awaitable[None]]


@dataclass(slots=True)
class CoordinatorContext:
    session_id: str
    user_id: str | None = None
    persona: str | None = None


class ConversationCoordinator:
    """所有入口应依赖的唯一对话编排门面。"""

    def __init__(self, runner: SessionAgentRunner) -> None:
        self._runner = runner

    async def stream_user_turn(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        user_id: str | None = None,
        persona: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式执行一轮请求，入口无需知道 Agent 如何创建。"""

        async for event in self._runner.stream(
            session_id,
            prompt,
            user_id=user_id,
            persona=persona,
        ):
            yield event

    async def handle_user_turn(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        user_id: str | None = None,
        persona: str | None = None,
    ) -> OrchestratedTurnResult:
        """非流式兼容接口，聚合文本事件后返回统一 DTO。"""

        chunks: list[str] = []
        steps = 0
        async for event in self.stream_user_turn(
            prompt,
            session_id=session_id,
            user_id=user_id,
            persona=persona,
        ):
            if isinstance(event, TextChunk):
                chunks.append(event.content)
            elif isinstance(event, ToolEvent) and event.phase == "start":
                steps += 1

        return OrchestratedTurnResult(
            response_text="".join(chunks),
            completed=True,
            delegated=False,
            status="completed",
            steps=steps,
            role_name=persona,
        )
