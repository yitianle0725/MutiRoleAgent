"""项目唯一的显式 ReAct Agent Runtime。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent.harness_events import INTERNAL_TOOL_NAMES

from .context import RunContext
from .answer_guard import AnswerabilityGate, AnswerValidator
from .evidence import EvidenceLedger
from .events import RunEvent
from .model_stream import LangChainStreamNormalizer, ModelDelta
from .request import RuntimeRequest
from .settlement import RunSettlementGate, RunTerminalResult
from .tool_scheduler import ToolScheduler
from .tool_policy import ToolPolicy, tool_policy
from .tool_contracts import ToolRequirement


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
        policy: ToolPolicy | None = None,
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
        self._policy = policy or tool_policy
        self._answerability = AnswerabilityGate()
        self._answer_validator = AnswerValidator()

    async def stream(
        self,
        request: RuntimeRequest,
        context: RunContext,
    ) -> AsyncIterator[RunEvent]:
        settlement = RunSettlementGate()
        messages = self._build_messages(request)
        requirement = self._policy.evaluate(
            request.prompt,
            {tool.name for tool in self._tools},
        )
        messages.insert(1 if messages and isinstance(messages[0], SystemMessage) else 0, SystemMessage(
            content=self._requirement_prompt(requirement)
        ))
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
                "tool_requirement": requirement.to_dict(),
            },
        )
        yield context.event(
            "tool_requirement_decided",
            requirement.to_dict(),
            visibility="debug",
        )

        try:
            async with asyncio.timeout(request.timeout_seconds):
                async for event in self._run_loop(
                    request, context, messages, requirement=requirement,
                ):
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
        *,
        requirement: ToolRequirement,
    ) -> AsyncIterator[RunEvent]:
        ledger = EvidenceLedger()
        tool_call_count = 0
        forced_tool_reminders = 0
        answer_repairs = 0
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
                        if requirement.evidence_required:
                            yield replace(event, visibility="private")
                        else:
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
                    if requirement.evidence_required:
                        yield replace(event, visibility="private")
                    else:
                        yield event

            if reasoning_started:
                yield context.event(
                    "reasoning_finished",
                    {"message_id": message_id},
                    visibility="private",
                )

            has_tools = bool(assistant_message.tool_calls)
            if text_started and (has_tools or not requirement.evidence_required):
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
                decision = self._answerability.evaluate(
                    requirement,
                    ledger,
                    fallback_available=bool(requirement.preferred_tools),
                )
                yield context.event(
                    "answerability_decided",
                    decision.to_dict(),
                    visibility="debug",
                )
                if decision.status in {"not_answerable", "needs_fallback"}:
                    if forced_tool_reminders < 1 and tool_call_count < requirement.max_tool_calls:
                        forced_tool_reminders += 1
                        messages.append(SystemMessage(content=(
                            "Runtime 拒绝了无证据答案。该请求必须先取得外部证据。"
                            f"优先工具：{', '.join(requirement.preferred_tools) or '任一合适检索工具'}。"
                            "请立即调用工具，不要继续直接回答。"
                        )))
                        yield context.event(
                            "round_finished",
                            {"round_id": round_id, "outcome": "evidence_required"},
                        )
                        continue
                    safe = self._answer_validator.safe_answer(decision)
                    async for event in self._safe_answer_events(context, message_id, safe):
                        yield event
                    yield context.event(
                        "round_finished", {"round_id": round_id, "outcome": "not_answerable"}
                    )
                    return

                valid, errors = self._answer_validator.validate(
                    visible_text, requirement, ledger,
                )
                if not valid and answer_repairs < 1:
                    answer_repairs += 1
                    yield context.event(
                        "answer_validation_failed",
                        {"errors": list(errors)},
                        visibility="debug",
                    )
                    messages.append(SystemMessage(content=(
                        "Runtime 校验未通过：" + "；".join(errors) + "。\n" +
                        ledger.prompt_block() + "\n请只基于这些证据重新回答，不得新增 URL。"
                    )))
                    yield context.event(
                        "round_finished", {"round_id": round_id, "outcome": "answer_repair"}
                    )
                    continue
                if not valid:
                    safe = self._answer_validator.safe_answer(decision)
                    async for event in self._safe_answer_events(context, message_id, safe):
                        yield event
                elif requirement.evidence_required:
                    async for event in self._safe_answer_events(
                        context, message_id, visible_text,
                    ):
                        yield event
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
                tool_call_count += 1
                if tool_call_count > requirement.max_tool_calls:
                    decision = self._answerability.evaluate(requirement, ledger)
                    safe = self._answer_validator.safe_answer(decision)
                    async for event in self._safe_answer_events(context, message_id, safe):
                        yield event
                    return
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
                execution = await self._tool_scheduler.execute(
                    {**tool_call, "id": tool_call_id},
                    requirement=requirement,
                    context=context,
                )
                preview = execution.content[:200]
                if execution.attempt > 1:
                    yield context.event(
                        "tool_call_retried",
                        {
                            "tool_call_id": execution.tool_call_id,
                            "tool_name": execution.tool_name,
                            "attempt": execution.attempt,
                        },
                    )
                yield context.event(
                    "tool_call_finished",
                    {
                        "tool_call_id": execution.tool_call_id,
                        "tool_name": execution.tool_name,
                        "status": execution.execution_status,
                        "execution_status": execution.execution_status,
                        "quality_status": execution.quality_status,
                        "attempt": execution.attempt,
                        "retryable": execution.retryable,
                        "fallback_required": execution.fallback_required,
                        "evidence_count": len(execution.evidence),
                        "result_preview": preview,
                        "duration_ms": round(execution.duration_ms, 2),
                    },
                    visibility=visibility,
                )
                yield context.event(
                    "tool_result_validated",
                    execution.to_dict(include_content=False),
                    visibility="debug",
                )
                added = ledger.add(execution.evidence)
                for item in added:
                    yield context.event(
                        "evidence_added",
                        item.to_dict(),
                        visibility="private",
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
                messages.append(self._tool_scheduler.to_message(execution))
                if execution.fallback_required:
                    yield context.event(
                        "fallback_started",
                        {"failed_tool": tool_name, "preferred_tools": list(requirement.preferred_tools)},
                    )

            yield context.event(
                "round_finished",
                {"round_id": round_id, "outcome": "tools_executed"},
            )
            messages.append(SystemMessage(content=ledger.prompt_block()))

        decision = self._answerability.evaluate(requirement, ledger)
        safe = self._answer_validator.safe_answer(decision)
        async for event in self._safe_answer_events(
            context, f"{context.run_id}:message:limit", safe,
        ):
            yield event

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
    def _requirement_prompt(requirement) -> str:
        if not requirement.evidence_required:
            return "Runtime policy：该请求不强制使用外部工具。"
        return (
            "Runtime policy：该请求必须取得外部证据后才能回答。\n"
            f"原因：{requirement.reason}\n"
            f"优先工具：{', '.join(requirement.preferred_tools) or '选择合适的已注册工具'}\n"
            f"必需字段：{', '.join(requirement.required_fields) or '与问题直接相关的事实'}\n"
            "工具失败、结果为空或字段缺失时必须明确说明，不得凭记忆补全。"
        )

    @staticmethod
    async def _safe_answer_events(context: RunContext, message_id: str, text: str):
        yield context.event("text_started", {"message_id": message_id})
        yield context.event("text_delta", {"message_id": message_id, "text": text})
        yield context.event(
            "text_finished", {"message_id": message_id, "role": "answer", "text": text}
        )

    @staticmethod
    def _text_hash(text: str) -> str:
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
