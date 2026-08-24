"""Session 与现有 LangGraph ReactAgent 的适配层。

P1 不复制 Agent 执行循环，runner 只负责按 session 隔离 Agent、统一锁和
异步调用边界。后续接入持久化 checkpointer 时只需替换内部 Agent 工厂。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agent.stream_events import StructuredData, TextChunk, ToolEvent


AgentFactory = Callable[[str, str | None, str | None], Awaitable[Any]]
StreamEvent = TextChunk | ToolEvent | StructuredData


class SessionAgentRunner:
    """按会话串行调用 Agent，避免入口直接操作 LangGraph 图。"""

    def __init__(self, agent_factory: AgentFactory) -> None:
        self._agent_factory = agent_factory
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            return self._locks.setdefault(session_id, asyncio.Lock())

    async def get_agent(
        self,
        session_id: str,
        *,
        user_id: str | None = None,
        persona: str | None = None,
    ) -> Any:
        return await self._agent_factory(session_id, user_id, persona)

    async def stream(
        self,
        session_id: str,
        prompt: str,
        *,
        user_id: str | None = None,
        persona: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """通过统一 runner 执行一轮流式请求。"""

        lock = await self._session_lock(session_id)
        async with lock:
            agent = await self.get_agent(
                session_id,
                user_id=user_id,
                persona=persona,
            )
            async for event in agent.execute_stream_async(prompt):
                yield event

    async def close_session(self, session_id: str) -> None:
        """释放会话锁对象，供会话删除时调用。"""

        async with self._locks_guard:
            self._locks.pop(session_id, None)
