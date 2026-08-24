"""统一对话编排边界。

P1 版本只做入口收敛和生命周期编排，Agent 业务仍由现有 LangGraph-backed
ReactAgent 执行。P2 再接入独立 RoleplayEngine 和事实结果包装。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent.results import AgentFactResult, OrchestratedTurnResult
from agent.request import AgentRequest
from agent.content import ContentBlock
from agent.stream_events import event_to_content_block
from agent.stream_events import StructuredData, TextChunk, ToolEvent
from agent.decision_engine import DecisionEngine, decision_engine as default_decision_engine
from memory.session_store import SessionStore, session_store as default_session_store

from .session_runner import SessionAgentRunner
from .roleplay import RoleplayEngine
from .runs import AgentRun, RunStore


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
        run_store: RunStore | None = None,
        decision: DecisionEngine | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self._runner = runner
        self._roleplay = roleplay or RoleplayEngine()
        self._runs = run_store or RunStore()
        self._decision = decision or default_decision_engine
        self._session_store = session_store or default_session_store
        if getattr(self._runner, "_session_store", None) is None:
            self._runner._session_store = self._session_store
        if getattr(self._runner, "_run_store", None) is None:
            self._runner._run_store = self._runs
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_locks_guard = asyncio.Lock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._tasks_lock = asyncio.Lock()
        self._completion_callbacks: dict[str, CompletionCallback] = {}

    @property
    def session_id(self) -> str:
        return self._runner_session_id if hasattr(self, "_runner_session_id") else "default"

    def execute_stream(self, prompt: str):
        """同步兼容 facade，供 Streamlit 等同步入口逐步迁移。"""

        async def collect():
            events = []
            async for event in self.stream_user_turn(prompt, session_id=self.session_id):
                events.append(event)
            return events

        return asyncio.run(collect())

    def bind_session(self, session_id: str) -> None:
        self._runner_session_id = session_id

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
        run_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式执行一轮请求，入口无需知道 Agent 如何创建。"""

        lock = await self._get_session_lock(session_id)
        async with lock:
            history = await asyncio.to_thread(self._session_store.get_history, session_id)
            decision = self._decision.evaluate(
                prompt,
                session_id=session_id,
                history=history,
            )
            if getattr(decision, "is_chat", False):
                response = await self._roleplay.chat_reply(
                    prompt, persona=persona, history=history[-8:]
                )
                await asyncio.to_thread(
                    self._session_store.append_pair, session_id, prompt, response
                )
                yield TextChunk(content=response)
                return

            async for event in self._runner.stream(
                session_id,
                prompt,
                user_id=user_id,
                persona=persona,
                run_id=run_id,
            ):
                yield event

    async def handle_user_turn_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[StreamEvent]:
        """EchoBot 风格命名的统一流式入口。"""

        async for event in self.stream_user_turn(*args, **kwargs):
            yield event

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._session_locks_guard:
            return self._session_locks.setdefault(session_id, asyncio.Lock())

    async def handle_user_turn(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        user_id: str | None = None,
        persona: str | None = None,
    ) -> OrchestratedTurnResult:
        """非流式兼容接口，聚合文本事件后返回统一 DTO。"""

        fact = await self._collect_fact(
            prompt, session_id=session_id, user_id=user_id, persona=persona
        )
        response_text = await self._present_fact(fact, prompt, persona)

        return OrchestratedTurnResult(
            response_text=response_text,
            completed=True,
            delegated=False,
            status="completed",
            steps=fact.steps,
            role_name=persona,
            fact_result=fact,
        )

    async def handle_request(self, request: AgentRequest) -> OrchestratedTurnResult:
        """消费统一 AgentRequest，避免新入口重复拼接参数。"""

        return await self.handle_user_turn(
            request.prompt,
            session_id=request.session_id,
            user_id=request.user_id,
            persona=request.persona,
        )

    async def start_agent_turn(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        user_id: str | None = None,
        persona: str | None = None,
        attempt: int = 1,
        completion_callback: CompletionCallback | None = None,
    ) -> OrchestratedTurnResult:
        """启动后台 Agent 任务，立即返回 ACK 和 run_id。"""

        thread_id = session_id
        run = await self._runs.create(
            session_id=session_id,
            thread_id=thread_id,
            prompt=prompt,
            attempt=attempt,
        )
        ack = await self._roleplay.delegated_ack(prompt, persona=persona)
        task = asyncio.create_task(
            self._run_background(
                run,
                user_id=user_id,
                persona=persona,
                completion_callback=completion_callback,
            ),
            name=f"agent-run-{run.run_id}",
        )
        async with self._tasks_lock:
            self._tasks[run.run_id] = task
            if completion_callback is not None:
                self._completion_callbacks[run.run_id] = completion_callback
        return OrchestratedTurnResult(
            response_text=ack,
            delegated=True,
            completed=False,
            run_id=run.run_id,
            status="running",
            role_name=persona,
        )

    async def get_run(self, run_id: str) -> AgentRun | None:
        return await self._runs.get(run_id)

    async def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        return await self._runs.read_events(run_id)

    async def get_agent_context(self, session_id: str) -> dict[str, Any]:
        """调试/管理入口：查看 Agent 专用历史摘要，不暴露给角色层。"""
        return await self._runner.get_context(session_id)

    async def recover_interrupted_runs(self) -> int:
        """服务启动时将遗留 running 任务标记为失败。"""
        return await self._runs.recover_interrupted()

    async def cancel_run(self, run_id: str) -> AgentRun | None:
        run = await self._runs.get(run_id)
        if run is None or run.status != "running":
            return run
        callback = self._completion_callbacks.get(run_id)
        async with self._tasks_lock:
            task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        updated = await self._runs.set_status(
            run_id, "cancelled", steps=run.steps, error="用户取消任务"
        )
        if callback and updated:
            fact = AgentFactResult(status="cancelled", text="用户取消任务")
            response = await self._roleplay.present_agent_cancelled(fact.text)
            await callback(OrchestratedTurnResult(response_text=response, completed=True, delegated=True, run_id=run_id, status="cancelled", fact_result=fact))
        return updated

    async def retry_run(self, run_id: str, *, user_id: str | None = None, persona: str | None = None) -> OrchestratedTurnResult:
        run = await self._runs.get(run_id)
        if run is None:
            raise ValueError(f"任务不存在：{run_id}")
        if run.status not in {"failed", "cancelled"}:
            raise ValueError("只有失败或已取消的任务可以重试")
        return await self.start_agent_turn(
            run.prompt,
            session_id=run.session_id,
            user_id=user_id,
            persona=persona,
            attempt=run.attempt + 1,
        )

    async def request_user_input(
        self,
        run_id: str,
        question: str,
        *,
        field: str = "answer",
        options: list[str] | None = None,
    ) -> AgentRun | None:
        """记录等待输入状态；后续由 LangGraph interrupt/resume 提供图恢复。"""

        run = await self._runs.get(run_id)
        if run is None:
            return None
        updated = await self._runs.set_status(
            run_id,
            "waiting_for_input",
            steps=run.steps,
            pending_user_input={
                "question": question,
                "field": field,
                "options": options or [],
                "thread_id": run.thread_id,
            },
        )
        callback = self._completion_callbacks.get(run_id)
        if callback and updated:
            fact = AgentFactResult(status="waiting_for_input", text=question, pending_user_input=updated.pending_user_input)
            response = await self._roleplay.present_waiting_for_input(question)
            await callback(OrchestratedTurnResult(response_text=response, completed=False, delegated=True, run_id=run_id, status="waiting_for_input", fact_result=fact))
        return updated

    async def _collect_fact(self, prompt: str, *, session_id: str, user_id: str | None, persona: str | None, run_id: str | None = None) -> AgentFactResult:
        chunks: list[str] = []
        tool_events: list[dict[str, Any]] = []
        content_blocks: list[ContentBlock] = []
        steps = 0
        async for event in self.stream_user_turn(prompt, session_id=session_id, user_id=user_id, persona=persona, run_id=run_id):
            content_blocks.append(event_to_content_block(event))
            if isinstance(event, TextChunk):
                chunks.append(event.content)
            elif isinstance(event, ToolEvent):
                if event.phase == "start":
                    steps += 1
                tool_events.append({"phase": event.phase, "tool_name": event.tool_name, "args": event.tool_args, "result_preview": event.result_preview})
        fact = AgentFactResult(status="completed", text="".join(chunks), content=content_blocks, tool_events=tool_events, steps=steps)
        for event in tool_events:
            preview = str(event.get("result_preview") or "")
            if preview.startswith(("[工具调用被拒绝]", "[工具执行失败]", "[参数错误]")):
                fact.add_error(preview)
        return fact

    async def _present_fact(self, fact: AgentFactResult, prompt: str, persona: str | None) -> str:
        return await self._roleplay.present_agent_result(fact, user_input=prompt, persona=persona)

    async def _run_background(
        self,
        run: AgentRun,
        *,
        user_id: str | None,
        persona: str | None,
        completion_callback: CompletionCallback | None = None,
    ) -> None:
        callback = completion_callback
        try:
            fact = await self._collect_fact(run.prompt, session_id=run.session_id, user_id=user_id, persona=persona, run_id=run.run_id)
            response = await self._present_fact(fact, run.prompt, persona)
            await self._runs.append_event(run.run_id, "run.result", {"response_text": response, "status": fact.status})
            await self._runs.set_status(run.run_id, "completed", steps=fact.steps, summary=fact.text[:1200])
            if callback:
                await callback(OrchestratedTurnResult(response_text=response, completed=True, delegated=True, run_id=run.run_id, status="completed", steps=fact.steps, role_name=persona, fact_result=fact))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            await self._runs.set_status(run.run_id, "failed", error=error)
            response = await self._roleplay.present_agent_failure(error, user_input=run.prompt, persona=persona)
            if callback:
                fact = AgentFactResult(status="failed", text=error, errors=[error])
                await callback(OrchestratedTurnResult(response_text=response, completed=True, delegated=True, run_id=run.run_id, status="failed", role_name=persona, fact_result=fact))
        finally:
            async with self._tasks_lock:
                self._tasks.pop(run.run_id, None)
                self._completion_callbacks.pop(run.run_id, None)
