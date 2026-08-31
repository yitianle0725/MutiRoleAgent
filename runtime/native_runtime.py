"""不依赖 LangGraph 的轻量 ReAct Agent Runtime。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent.harness_events import INTERNAL_TOOL_NAMES

from .context import RunContext
from .events import RunEvent
from .model_stream import LangChainStreamNormalizer, ModelDelta
from .request import RuntimeRequest
from .settlement import RunSettlementGate, RunTerminalResult
from .tool_scheduler import ToolScheduler


def _history_messages(history: list[dict[str, Any]]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            from langchain_core.messages import AIMessage

            messages.append(AIMessage(content=content))
        elif role == "system":
            messages.append(SystemMessage(content=content))
    return messages


class NativeAgentRuntime:
    """显式控制模型流、工具循环、取消和事件生命周期。"""

    def __init__(
        self,
        model: Any,
        tools: list[BaseTool],
        *,
        system_prompt: str = "",
        tool_timeout_seconds: float = 30.0,
    ) -> None:
        self._model_name = str(
            getattr(model, "model_name", None)
            or getattr(model, "model", None)
            or type(model).__name__
        )
        self._model = model.bind_tools(tools) if tools else model
        self._tools = tools
        self._system_prompt = system_prompt
        self._tool_scheduler = ToolScheduler(
            tools,
            timeout_seconds=tool_timeout_seconds,
        )

    async def stream(
        self,
        request: RuntimeRequest,
        context: RunContext,
    ) -> AsyncIterator[RunEvent]:
        settlement = RunSettlementGate()
        messages = self._build_messages(request)
        runtime_context = str(request.metadata.get("runtime_context") or "")
        yield context.event(
            "run_started",
            {
                "session_id": context.session_id,
                "runtime": "native",
                "model": self._model_name,
                "max_rounds": request.max_rounds,
                "tool_names": [tool.name for tool in self._tools],
                "system_prompt_hash": self._text_hash(self._system_prompt),
                "runtime_context_hash": self._text_hash(runtime_context),
                "context_sources": list(request.metadata.get("context_sources", [])),
            },
        )

        try:
            async with asyncio.timeout(request.timeout_seconds):
                async for event in self._run_loop(request, context, messages):
                    yield event
            terminal = RunTerminalResult(
                status="cancelled" if context.cancelled else "completed"
            )
            if settlement.try_settle(terminal):
                yield context.event("run_finished", {"status": terminal.status})
        except TimeoutError as error:
            terminal = RunTerminalResult(status="timeout", error=str(error))
            if settlement.try_settle(terminal):
                yield context.event(
                    "run_failed",
                    {"status": "timeout", "error": "Agent 运行超时"},
                )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            terminal = RunTerminalResult(status="failed", error=message)
            if settlement.try_settle(terminal):
                yield context.event(
                    "run_failed",
                    {"status": "failed", "error": message},
                )

    async def _run_loop(
        self,
        request: RuntimeRequest,
        context: RunContext,
        messages: list[BaseMessage],
    ) -> AsyncIterator[RunEvent]:
        for round_index in range(1, request.max_rounds + 1):
            if context.cancelled:
                return

            round_id = f"{context.run_id}:round:{round_index}"
            message_id = f"{context.run_id}:message:{round_index}"
            yield context.event(
                "round_started",
                {"round_id": round_id, "round_index": round_index},
            )
            yield context.event("model_started", {"round_id": round_id})
            model_started_at = perf_counter()

            normalizer = LangChainStreamNormalizer()
            visible_text = ""
            text_started = False
            reasoning_started = False

            async for chunk in self._model.astream(messages):
                if context.cancelled:
                    return
                if not isinstance(chunk, AIMessageChunk):
                    chunk = AIMessageChunk(content=str(getattr(chunk, "content", chunk)))
                for delta in normalizer.apply(chunk):
                    async for event in self._delta_events(
                        delta,
                        context,
                        message_id,
                        text_started=text_started,
                        reasoning_started=reasoning_started,
                    ):
                        if event.type == "text_started":
                            text_started = True
                        elif event.type == "reasoning_started":
                            reasoning_started = True
                        if event.type == "text_delta":
                            visible_text += str(event.data.get("text", ""))
                        yield event

            final_deltas, assistant_message = normalizer.finish()
            for delta in final_deltas:
                async for event in self._delta_events(
                    delta,
                    context,
                    message_id,
                    text_started=text_started,
                    reasoning_started=reasoning_started,
                ):
                    if event.type == "text_started":
                        text_started = True
                    elif event.type == "reasoning_started":
                        reasoning_started = True
                    if event.type == "text_delta":
                        visible_text += str(event.data.get("text", ""))
                    yield event

            if reasoning_started:
                yield context.event(
                    "reasoning_finished",
                    {"message_id": message_id},
                    visibility="private",
                )

            has_tools = bool(assistant_message.tool_calls)
            if text_started:
                yield context.event(
                    "text_finished",
                    {
                        "message_id": message_id,
                        "role": "activity" if has_tools else "answer",
                        "text": visible_text,
                    },
                )
            yield context.event(
                "model_finished",
                {
                    "round_id": round_id,
                    "has_tool_calls": has_tools,
                    "duration_ms": round((perf_counter() - model_started_at) * 1000, 2),
                },
            )
            messages.append(assistant_message)

            if not has_tools:
                yield context.event(
                    "round_finished",
                    {"round_id": round_id, "outcome": "answer"},
                )
                return

            for tool_call in assistant_message.tool_calls:
                if context.cancelled:
                    return
                tool_name = str(tool_call.get("name") or "")
                tool_call_id = str(tool_call.get("id") or uuid.uuid4().hex)
                visibility = "private" if tool_name in INTERNAL_TOOL_NAMES else "public"
                yield context.event(
                    "tool_call_started",
                    {
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "tool_args": tool_call.get("args") or {},
                    },
                    visibility=visibility,
                )
                execution = await self._tool_scheduler.execute({
                    **tool_call,
                    "id": tool_call_id,
                })
                preview = execution.content[:200]
                yield context.event(
                    "tool_call_finished",
                    {
                        "tool_call_id": execution.tool_call_id,
                        "tool_name": execution.tool_name,
                        "status": execution.status,
                        "result_preview": preview,
                        "duration_ms": round(execution.duration_ms, 2),
                    },
                    visibility=visibility,
                )
                yield context.event(
                    "tool_result",
                    {
                        "tool_call_id": execution.tool_call_id,
                        "tool_name": execution.tool_name,
                        "content": execution.content,
                    },
                    visibility="private",
                )
                messages.append(execution.to_message())

            yield context.event(
                "round_finished",
                {"round_id": round_id, "outcome": "tools_executed"},
            )

        raise RuntimeError(f"超过最大轮数：{request.max_rounds}")

    async def _delta_events(
        self,
        delta: ModelDelta,
        context: RunContext,
        message_id: str,
        *,
        text_started: bool,
        reasoning_started: bool,
    ) -> AsyncIterator[RunEvent]:
        if delta.type == "text_delta":
            if not text_started:
                yield context.event("text_started", {"message_id": message_id})
            yield context.event(
                "text_delta",
                {"message_id": message_id, "text": str(delta.data.get("text", ""))},
            )
        elif delta.type == "reasoning_delta":
            if not reasoning_started:
                yield context.event(
                    "reasoning_started",
                    {"message_id": message_id},
                    visibility="private",
                )
            yield context.event(
                "reasoning_delta",
                {"message_id": message_id, "text": str(delta.data.get("text", ""))},
                visibility="private",
            )
        elif delta.type == "tool_args_delta":
            yield context.event("tool_args_delta", dict(delta.data), visibility="debug")
        elif delta.type == "usage":
            yield context.event("usage_updated", dict(delta.data), visibility="debug")

    def _build_messages(self, request: RuntimeRequest) -> list[BaseMessage]:
        runtime_prompt = str(request.metadata.get("runtime_context") or "")
        system_parts = [part for part in (self._system_prompt, runtime_prompt) if part]
        messages: list[BaseMessage] = []
        if system_parts:
            messages.append(SystemMessage(content="\n\n---\n\n".join(system_parts)))
        messages.extend(_history_messages(request.history))
        messages.append(HumanMessage(content=request.prompt))
        return messages

    @staticmethod
    def _text_hash(text: str) -> str:
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
