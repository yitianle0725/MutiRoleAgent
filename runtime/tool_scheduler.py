"""Native Runtime 唯一的工具执行、超时、重试和结果验证入口。"""

from __future__ import annotations

import asyncio
import json
import random
from time import perf_counter
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from agent.action_gate import action_gate
from agent.execution_policy import validate_tool_args

from .context import RunContext
from .result_validator import ResultValidator
from .tool_contracts import ToolRequirement, ToolResultEnvelope


def _result_text(value: Any) -> str:
    if isinstance(value, ToolMessage):
        return str(value.content)
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


class ToolScheduler:
    """所有执行路径共用的工具事务边界。"""

    def __init__(
        self,
        tools: list[BaseTool],
        *,
        timeout_seconds: float = 30.0,
        validator: ResultValidator | None = None,
    ) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.timeout_seconds = max(float(timeout_seconds), 1.0)
        self._validator = validator or ResultValidator()

    async def execute(
        self,
        tool_call: dict[str, Any],
        *,
        requirement: ToolRequirement | None = None,
        context: RunContext | None = None,
    ) -> ToolResultEnvelope:
        requirement = requirement or ToolRequirement()
        tool_name = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or f"{tool_name}-unknown")
        arguments = tool_call.get("args")
        tool_args = arguments if isinstance(arguments, dict) else {}
        started_at = perf_counter()

        if context and context.cancelled:
            return self._failure(
                tool_call_id, tool_name, "cancelled", "cancelled",
                "用户已取消运行", started_at,
            )
        tool = self._tools.get(tool_name)
        if tool is None:
            return self._failure(
                tool_call_id, tool_name, "rejected", "unknown_tool",
                f"未注册工具：{tool_name}", started_at,
            )
        if requirement.allowed_tools and tool_name not in requirement.allowed_tools:
            return self._failure(
                tool_call_id, tool_name, "rejected", "tool_not_allowed",
                f"当前请求不允许调用工具：{tool_name}", started_at,
            )

        gate_result = action_gate.check_tool_call(tool_name, tool_args)
        if not gate_result.allow:
            return self._failure(
                tool_call_id, tool_name, "rejected", "action_gate_rejected",
                gate_result.reason, started_at,
            )
        policy_result = validate_tool_args(tool_name, tool_args)
        if not policy_result.valid:
            return self._failure(
                tool_call_id, tool_name, "invalid_arguments", "invalid_arguments",
                policy_result.error_message, started_at,
            )

        max_attempts = max(requirement.max_attempts_per_tool, 1)
        last: ToolResultEnvelope | None = None
        for attempt in range(1, max_attempts + 1):
            if context and context.cancelled:
                return self._failure(
                    tool_call_id, tool_name, "cancelled", "cancelled",
                    "用户已取消运行", started_at, attempt=attempt,
                )
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    cancelled, value = await self._invoke_with_cancel(
                        tool, tool_args, context,
                    )
                if cancelled:
                    return self._failure(
                        tool_call_id, tool_name, "cancelled", "cancelled",
                        "用户已取消运行", started_at, attempt=attempt,
                    )
                content = _result_text(value)
                quality, data, evidence, fallback, validation_error = self._validator.validate(
                    tool_name,
                    content,
                    official_only=requirement.official_only,
                )
                result = ToolResultEnvelope(
                    tool_call_id=tool_call_id,
                    tool_name=tool_name,
                    execution_status="completed",
                    quality_status=quality,
                    content=content,
                    data=data,
                    evidence=evidence,
                    error_code="result_validation_failed" if validation_error else None,
                    error_message=validation_error,
                    retryable=self._content_is_transient(validation_error),
                    fallback_required=fallback or quality in {"empty", "source_mismatch"},
                    attempt=attempt,
                    duration_ms=(perf_counter() - started_at) * 1000,
                )
                if result.retryable and attempt < max_attempts:
                    last = result
                    await asyncio.sleep(
                        min(0.25 * (2 ** (attempt - 1)) + random.random() * 0.1, 1.0)
                    )
                    continue
                return result
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                last = self._failure(
                    tool_call_id, tool_name, "timeout", "timeout",
                    f"{tool_name} 执行超时", started_at,
                    retryable=True, attempt=attempt,
                )
            except (ConnectionError, OSError) as error:
                last = self._failure(
                    tool_call_id, tool_name, "connection_error", "connection_error",
                    f"{type(error).__name__}: {str(error)[:200]}", started_at,
                    retryable=True, attempt=attempt,
                )
            except Exception as error:
                retryable = self._is_transient(error)
                last = self._failure(
                    tool_call_id, tool_name,
                    "connection_error" if retryable else "internal_error",
                    "transient_error" if retryable else "tool_error",
                    f"{type(error).__name__}: {str(error)[:200]}", started_at,
                    retryable=retryable, attempt=attempt,
                )
            if not last.retryable or attempt >= max_attempts:
                return last
            await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)) + random.random() * 0.1, 1.0))

        assert last is not None
        return last

    @staticmethod
    async def _invoke_with_cancel(
        tool: BaseTool,
        tool_args: dict[str, Any],
        context: RunContext | None,
    ) -> tuple[bool, Any]:
        invoke_task = asyncio.create_task(tool.ainvoke(tool_args))
        if context is None:
            return False, await invoke_task
        cancel_task = asyncio.create_task(context.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {invoke_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done and context.cancelled:
                return True, None
            return False, await invoke_task
        finally:
            for task in (invoke_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(invoke_task, cancel_task, return_exceptions=True)

    @staticmethod
    def to_message(result: ToolResultEnvelope) -> ToolMessage:
        payload = {
            "execution_status": result.execution_status,
            "quality_status": result.quality_status,
            "data": result.data,
            "evidence": [item.to_dict() for item in result.evidence],
            "error": result.error_message,
            "fallback_required": result.fallback_required,
        }
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False, default=str),
            tool_call_id=result.tool_call_id,
            name=result.tool_name,
        )

    @staticmethod
    def _is_transient(error: Exception) -> bool:
        text = f"{type(error).__name__} {error}".lower()
        return any(token in text for token in (
            "timeout", "connection", "temporarily", "rate limit", "429",
            "502", "503", "504", "network",
        ))

    @staticmethod
    def _content_is_transient(message: str | None) -> bool:
        if not message:
            return False
        text = message.lower()
        return any(token in text for token in (
            "timeout", "connection", "network", "temporarily", "rate limit",
            "429", "502", "503", "504", "apiconnectionerror",
        ))

    @staticmethod
    def _failure(
        tool_call_id: str,
        tool_name: str,
        execution_status,
        error_code: str,
        message: str,
        started_at: float,
        *,
        retryable: bool = False,
        attempt: int = 1,
    ) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            execution_status=execution_status,
            quality_status="unverified",
            content=f"[工具执行失败] {message}",
            error_code=error_code,
            error_message=message,
            retryable=retryable,
            fallback_required=execution_status in {"timeout", "connection_error"},
            attempt=attempt,
            duration_ms=(perf_counter() - started_at) * 1000,
        )
