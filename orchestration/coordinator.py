"""统一对话编排边界。

P1 版本只做入口收敛和生命周期编排，Agent 业务仍由现有 LangGraph-backed
ReactAgent 执行。P2 再接入独立 RoleplayEngine 和事实结果包装。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent.results import AgentFactResult, OrchestratedTurnResult
from agent.stream_events import StructuredData, TextChunk, ToolEvent

from .session_runner import SessionAgentRunner
from .roleplay import RoleplayEngine


StreamEvent = TextChunk | ToolEvent | StructuredData
CompletionCallback = Callable[[OrchestratedTurnResult], Awaitable[None]]


@dataclass(slots=True)
class CoordinatorContext:
    session_id: str
    user_id: str | None = None
    persona: str | None = None


class ConversationCoordinator:
    """所有入口应依赖的唯一对话编排门面。"""

    def __init__(
        self,
        runner: SessionAgentRunner,
        roleplay: RoleplayEngine | None = None,
    ) -> None:
        self._runner = runner
        self._roleplay = roleplay or RoleplayEngine()

    async def chat_reply(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        persona: str | None = None,
    ) -> str:
        """轻量角色聊天入口；不加载工具。"""

        return await self._roleplay.chat_reply(prompt, persona=persona)

    async def delegated_ack(
        self,
        prompt: str,
        *,
        persona: str | None = None,
    ) -> str:
        """复杂任务的第一阶段响应。P4 再接入后台 run 生命周期。"""

        return await self._roleplay.delegated_ack(prompt, persona=persona)

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
        tool_events: list[dict[str, Any]] = []
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
                tool_events.append({
                    "phase": event.phase,
                    "tool_name": event.tool_name,
                    "args": event.tool_args,
                })

        fact = AgentFactResult(
            status="completed",
            text="".join(chunks),
            tool_events=tool_events,
            steps=steps,
        )
        response_text = await self._roleplay.present_agent_result(
            fact,
            user_input=prompt,
            persona=persona,
        )

        return OrchestratedTurnResult(
            response_text=response_text,
            completed=True,
            delegated=False,
            status="completed",
            steps=steps,
            role_name=persona,
            fact_result=fact,
        )
