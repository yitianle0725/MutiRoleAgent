"""Session 与现有 LangGraph ReactAgent 的适配层。

P1 不复制 Agent 执行循环，runner 只负责按 session 隔离 Agent、统一锁和
异步调用边界。后续接入持久化 checkpointer 时只需替换内部 Agent 工厂。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agent.stream_events import StructuredData, TextChunk, ToolEvent
from memory.session_store import SessionStore
from orchestration.runs import RunStore


AgentFactory = Callable[[str, str | None, str | None], Awaitable[Any]]
StreamEvent = TextChunk | ToolEvent | StructuredData


class SessionAgentRunner:
    """按会话串行调用 Agent，避免入口直接操作 LangGraph 图。"""

    def __init__(
        self,
        agent_factory: AgentFactory,
        *,
        session_store: SessionStore | None = None,
        run_store: RunStore | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._session_store = session_store
        self._run_store = run_store
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
        run_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """通过统一 runner 执行一轮流式请求。"""

        lock = await self._session_lock(session_id)
        async with lock:
            agent = await self.get_agent(
                session_id,
                user_id=user_id,
                persona=persona,
            )
            # Agent 内部的可见历史由 ReactAgent 维护；Runner 只补充 Agent 专用审计历史。
            agent_history = []
            if self._session_store is not None:
                agent_history = await asyncio.to_thread(self._session_store.get_agent_history, session_id)
            async for event in agent.execute_stream_async(prompt):
                if self._run_store is not None and run_id is not None:
                    await self._run_store.append_event(run_id, "agent.event", _event_record(event))
                if isinstance(event, ToolEvent):
                    agent_history.append(event)
                yield event
            if self._session_store is not None and agent_history:
                # ToolEvent 不是 LangChain BaseMessage，摘要只保存可序列化文本。
                summary = "\n".join(str(item) for item in agent_history[-20:])
                await asyncio.to_thread(self._session_store.set_agent_summary, session_id, summary[:4000])

    async def close_session(self, session_id: str) -> None:
        """释放会话锁对象，供会话删除时调用。"""

        async with self._locks_guard:
            self._locks.pop(session_id, None)


def _event_record(event: StreamEvent) -> dict[str, Any]:
    """把流式事件转换为 RunStore 可持久化的简单字典。"""
    if isinstance(event, TextChunk):
        return {"type": "text", "content": event.content}
    if isinstance(event, ToolEvent):
        return {
            "type": "tool",
            "phase": event.phase,
            "tool_name": event.tool_name,
            "args": event.tool_args,
            "result_preview": event.result_preview,
        }
    return {"type": "structured", "schema_type": event.schema_type, "data": event.raw_json}
