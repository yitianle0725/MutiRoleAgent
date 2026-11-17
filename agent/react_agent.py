"""项目自研 Agent Runtime 的会话级入口。"""

from __future__ import annotations

import asyncio
import os
import queue
import threading
import time
import uuid
from contextlib import aclosing
from typing import Any

from model.factory import chat_model
from utils.config_handler import agent_config
from utils.conversation_tracer import ConversationTracer
from utils.logger_handler import logger
from utils.performance_monitor import PerformanceMonitor
from observability.store import monitor_store
from memory.chat_db import chat_db
from memory.context_trimmer import estimate_tokens, history_stats, trim_history
from memory.l2_memory import l2_memory_store
from memory.session_store import session_store
from runtime.context import RunContext
from runtime.events import RunEvent
from runtime.legacy_adapter import LegacyEventStreamAdapter
from runtime.native_runtime import NativeAgentRuntime
from runtime.request import RuntimeRequest
from agent.action_gate import action_gate
from agent.harness_events import HarnessEvent
from skill_support import SKILL_TOOLS, get_skill_registry, init_skills
from tools.agent_tools import (
    fetch_anime,
    fetch_novel,
    get_current_time,
    get_public_ip,
    get_season_anime,
    maps_ip_location,
    maps_weather,
    rag_summarize,
    search_anime,
    search_game_official,
    search_novel,
)
from tools.mcp_client import mcp_manager
from tools.novel_tools import download_novel


_CONTEXT_CONFIG = agent_config.get("context", {})
TRIM_MAX_TOKENS = int(_CONTEXT_CONFIG.get("trim_max_tokens", 6000))
TRIM_MAX_ROUNDS = int(_CONTEXT_CONFIG.get("trim_max_rounds", 15))
LLM_TURN_TIMEOUT = float(_CONTEXT_CONFIG.get("llm_turn_timeout", 90))
TURN_QUEUE_TIMEOUT = float(_CONTEXT_CONFIG.get("turn_queue_timeout", 5))


def classify_ai_content(message: Any) -> str | None:
    """按工具调用判断模型文本是过程说明还是最终答案。"""

    if not getattr(message, "content", None):
        return None
    return "process_text" if getattr(message, "tool_calls", None) else "final_text"


class ReactAgent:
    """按 Session 封装 NativeAgentRuntime、上下文和持久化。"""

    def __init__(
        self,
        session_id: str = "default",
        user_id: str | None = None,
        default_persona: str | None = None,
        *,
        external_persistence: bool = False,
    ) -> None:
        self.session_id = session_id
        self.user_id = user_id
        self.default_persona = default_persona
        self.external_persistence = external_persistence
        self.thread_id = session_id
        self.native_runtime: NativeAgentRuntime | None = None
        self._runtime_context = ""
        self._turn_lock = threading.Lock()
        self._initialized = False
        self._turn_started_at = 0.0
        self._turn_snapshot_start = None
        self._current_tracer: ConversationTracer | None = None
        self._current_route = "native"
        self._current_outcome = "success"
        self.performance_monitor = PerformanceMonitor()

    async def init_agent(self) -> None:
        """加载 Persona、Skill、MCP 工具并创建唯一 Native Runtime。"""

        if self._initialized:
            return
        from agent.persona.engine import persona_engine

        await asyncio.to_thread(persona_engine.reload_personas_from_disk)
        weather_tools = [maps_weather]
        if os.getenv("DASHSCOPE_API_KEY"):
            try:
                loaded = await mcp_manager.get_domain_tools("amap")
                if loaded:
                    weather_tools = loaded
            except Exception as error:
                logger.warning("AMap MCP 加载失败，使用本地天气工具: %s", error)

        websearch_tools: list[Any] = []
        try:
            websearch_tools = await mcp_manager.get_domain_tools("websearch")
        except Exception as error:
            logger.warning("WebSearch MCP 加载失败: %s", error)

        local_tools = [
            search_anime, fetch_anime, get_season_anime,
            search_novel, fetch_novel, search_game_official,
            rag_summarize, get_public_ip, get_current_time, download_novel,
        ]
        raw_tools = (
            local_tools + list(SKILL_TOOLS) + weather_tools
            + [maps_ip_location] + websearch_tools
        )
        tools = action_gate.filter_tools(raw_tools, context={"user_id": self.user_id})

        try:
            await init_skills()
            skills_summary = get_skill_registry().build_skills_summary()
        except Exception as error:
            logger.warning("Skill 系统加载失败: %s", error)
            skills_summary = ""

        from prompts.composer import compose_prompt

        system_prompt = compose_prompt(
            persona=self.default_persona,
            skills_summary=skills_summary,
        )
        self.native_runtime = NativeAgentRuntime(
            chat_model,
            tools,
            system_prompt=system_prompt,
        )
        await asyncio.to_thread(chat_db.init_db)
        await asyncio.to_thread(chat_db.load_session_into_store, self.session_id, session_store)
        self._initialized = True
        logger.info("Native Agent Runtime 已初始化，工具数=%d", len(tools))

    def set_runtime_context(self, context: str) -> None:
        self._runtime_context = str(context or "")

    async def execute_runtime_stream_async(
        self,
        query: str,
        *,
        run_context: RunContext,
    ):
        """执行唯一 Native 运行链并产出 Runtime v2 事件。"""

        acquisition = asyncio.create_task(asyncio.to_thread(
            self._turn_lock.acquire, True, TURN_QUEUE_TIMEOUT,
        ))
        try:
            acquired = await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            if await acquisition:
                self._turn_lock.release()
            raise
        if not acquired:
            self.performance_monitor.record_rejection()
            raise RuntimeError("正在处理上一条消息，请等待其完成后再发送。")

        try:
            self._turn_started_at = time.perf_counter()
            self._turn_snapshot_start = self.performance_monitor.snapshot()
            self._current_outcome = "success"
            self.performance_monitor.start_turn()
            async with aclosing(self._execute_native_runtime_locked(query, run_context)) as events:
                async for event in events:
                    self._observe_event(event)
                    yield event
        except (asyncio.CancelledError, GeneratorExit):
            self._current_outcome = "cancelled"
            raise
        except Exception:
            self._current_outcome = "error"
            raise
        finally:
            self.performance_monitor.finish_turn(self._current_outcome)
            self._enqueue_turn_observation()
            self._turn_lock.release()

    async def _execute_native_runtime_locked(
        self,
        query: str,
        run_context: RunContext,
    ):
        if not self._initialized:
            await self.init_agent()
        if self.native_runtime is None:
            raise RuntimeError("Native Runtime 尚未初始化")

        tracer = ConversationTracer(session_id=self.session_id, trace_id=run_context.run_id)
        self._current_tracer = tracer
        tracer.enter(query)
        raw_history = await asyncio.to_thread(session_store.get_history, self.session_id)
        tracer.load_history(raw_history)
        trimmed = trim_history(
            raw_history,
            max_tokens=TRIM_MAX_TOKENS,
            max_rounds=TRIM_MAX_ROUNDS,
        )
        tracer.after_trim(raw_history, trimmed)
        tracer.decision("work", 1.0, "native_runtime")

        l2_context = ""
        if self.user_id and not self.external_persistence:
            l2_context = await asyncio.to_thread(
                l2_memory_store.build_prompt_block,
                self.user_id,
                query,
            )
        runtime_context = "\n\n---\n\n".join(
            part for part in (l2_context, self._runtime_context) if part
        )
        history = [
            {
                "role": self._message_role(message),
                "content": self._extract_content(message),
            }
            for message in trimmed
            if getattr(message, "type", "") in {"human", "ai", "system"}
        ]
        request = RuntimeRequest(
            session_id=self.session_id,
            prompt=query,
            user_id=self.user_id,
            persona=self.default_persona,
            history=history,
            max_rounds=int(agent_config.get("max_steps", 20)),
            timeout_seconds=LLM_TURN_TIMEOUT,
            metadata={
                "runtime_context": runtime_context,
                "context_sources": [
                    "system_prompt", "session_mode", "user_profile", "session_memory",
                ],
            },
        )

        final_response = ""
        active_skill: str | None = None
        terminal: RunEvent | None = None
        tracer.agent_path_start(len(history) + 1)
        async with aclosing(self.native_runtime.stream(request, run_context)) as events:
            async for event in events:
                if event.type == "tool_call_started":
                    tool_name = str(event.data.get("tool_name", ""))
                    tracer.agent_tool_call(tool_name)
                    if tool_name == "invoke_skill":
                        args = event.data.get("tool_args", {})
                        if isinstance(args, dict):
                            active_skill = str(args.get("skill_name") or "") or active_skill
                elif event.type == "text_finished" and event.data.get("role") == "answer":
                    final_response = str(event.data.get("text", ""))
                elif event.type in {"run_finished", "run_failed"}:
                    terminal = event
                    continue
                yield event

        if active_skill and final_response:
            structured = await self._postprocess_structured(final_response, active_skill)
            if structured is not None:
                yield run_context.event(
                    "structured_data",
                    {"schema_type": structured.schema_type, "data": structured.raw_json},
                )
        tracer.agent_path_done(len(final_response), {})
        if final_response and not self.external_persistence:
            await asyncio.to_thread(
                session_store.append_pair, self.session_id, query, final_response,
            )
            await asyncio.to_thread(chat_db.save_pair, self.session_id, query, final_response)
        tracer.exit()
        if terminal is not None:
            yield terminal

    def _observe_event(self, event: RunEvent) -> None:
        if event.type == "run_failed":
            self._current_outcome = str(event.data.get("status") or "error")
        elif event.type == "run_finished" and event.data.get("status") == "cancelled":
            self._current_outcome = "cancelled"
        elif event.type == "text_delta" and event.visibility == "public":
            self.performance_monitor.record_visible_text(
                estimate_tokens(str(event.data.get("text", "")))
            )
        elif event.type == "tool_call_started":
            self.performance_monitor.record_step(1)
        elif event.type == "tool_call_finished":
            self.performance_monitor.record_tool_call(
                float(event.data.get("duration_ms", 0)) / 1000,
                success=event.data.get("execution_status") == "completed",
            )

    @staticmethod
    def _message_role(message: Any) -> str:
        return {"human": "user", "ai": "assistant"}.get(
            getattr(message, "type", ""), "system",
        )

    @staticmethod
    def _extract_content(message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        return str(content or "").strip()

    @staticmethod
    async def _postprocess_structured(full_response: str, skill_name: str):
        try:
            from agent.structured_output import process_structured_output
            from agent.structured_output.retry import retry_handler

            result = process_structured_output(full_response, skill_name=skill_name)
            if result is not None and result.valid:
                return result
            if result is not None and retry_handler.should_retry(result):
                return await retry_handler.retry_async(
                    full_response, result, context={"skill": skill_name},
                )
        except Exception as error:
            logger.debug("结构化输出后处理跳过: %s", error)
        return None

    def clear_history(self) -> None:
        session_store.clear(self.session_id)
        chat_db.clear_session(self.session_id)

    def get_history_info(self) -> dict[str, Any]:
        stats = history_stats(session_store.get_history(self.session_id))
        return {
            "session_id": self.session_id,
            "message_count": stats["total_messages"],
            "round_count": stats["total_rounds"],
            "estimated_tokens": stats["estimated_tokens"],
            "performance": self.performance_monitor.snapshot(),
        }

    def get_last_turn_observation(self) -> dict[str, str]:
        return {
            "trace_id": self._current_tracer.trace_id if self._current_tracer else "",
            "route": self._current_route,
            "outcome": self._current_outcome,
        }

    def _enqueue_turn_observation(self) -> None:
        tracer = self._current_tracer
        baseline = self._turn_snapshot_start
        if tracer is None or baseline is None:
            return
        current = self.performance_monitor.snapshot()
        monitor_store.enqueue_turn({
            "trace_id": tracer.trace_id,
            "session_id": self.session_id,
            "route": self._current_route,
            "outcome": self._current_outcome,
            "duration_ms": round((time.perf_counter() - self._turn_started_at) * 1000, 2),
            "input_tokens": current.input_tokens - baseline.input_tokens,
            "output_tokens": current.output_tokens - baseline.output_tokens,
            "tool_calls": current.tool_calls - baseline.tool_calls,
            "execution_steps": current.execution_steps - baseline.execution_steps,
            "error_type": "" if self._current_outcome == "success" else self._current_outcome,
            "events": tracer.export_events(),
        })

    async def execute_stream_async(self, query: str, *, run_id: str | None = None):
        """兼容旧 UI 的 HarnessEvent 输出，内部仍只执行 Native Runtime。"""

        context = RunContext(
            session_id=self.session_id,
            run_id=run_id or uuid.uuid4().hex,
            thread_id=self.thread_id,
        )
        adapter = LegacyEventStreamAdapter()
        async for event in self.execute_runtime_stream_async(query, run_context=context):
            for legacy in adapter.feed(event):
                yield legacy

    def execute_stream(self, query: str):
        result_queue: queue.Queue = queue.Queue()

        async def run() -> None:
            try:
                async for event in self.execute_stream_async(query):
                    result_queue.put(("event", event))
            except Exception as error:
                result_queue.put(("error", error))
            finally:
                result_queue.put(("done", None))

        thread = threading.Thread(target=lambda: asyncio.run(run()), daemon=True)
        thread.start()
        while True:
            try:
                kind, value = result_queue.get(timeout=300)
            except queue.Empty:
                yield HarnessEvent(type="run_end", data={"status": "timeout"})
                break
            if kind == "done":
                break
            if kind == "error":
                yield HarnessEvent(
                    type="run_end",
                    data={"status": "failed", "error": f"{type(value).__name__}: {value}"},
                )
                break
            yield value
        thread.join(timeout=5)

    def execute_stream_text(self, query: str):
        for event in self.execute_stream(query):
            if event.type == "final_text":
                yield str(event.data.get("text", ""))


def _ensure_init() -> ReactAgent:
    agent = ReactAgent()
    asyncio.run(agent.init_agent())
    return agent


async def main() -> None:
    agent = ReactAgent(session_id="test_session")
    await agent.init_agent()
    async for result in agent.execute_stream_async("查询我当地的实时气温"):
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
