"""Native Runtime 使用的工具查找、校验和异步执行。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from agent.action_gate import action_gate
from agent.execution_policy import validate_tool_args


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_call_id: str
    tool_name: str
    content: str
    status: str
    duration_ms: float

    def to_message(self) -> ToolMessage:
        return ToolMessage(
            content=self.content,
            tool_call_id=self.tool_call_id,
            name=self.tool_name,
        )


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
    """执行已经由模型确定的工具调用，保留安全检查和超时边界。"""

    def __init__(self, tools: list[BaseTool], *, timeout_seconds: float = 30.0) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.timeout_seconds = max(float(timeout_seconds), 1.0)

    async def execute(self, tool_call: dict[str, Any]) -> ToolExecutionResult:
        tool_name = str(tool_call.get("name") or "")
        tool_call_id = str(tool_call.get("id") or f"{tool_name}-unknown")
        arguments = tool_call.get("args")
        tool_args = arguments if isinstance(arguments, dict) else {}
        started_at = perf_counter()

        tool = self._tools.get(tool_name)
        if tool is None:
            return self._failure(
                tool_call_id,
                tool_name,
                f"[工具执行失败] 未注册工具：{tool_name}",
                started_at,
            )

        gate_result = action_gate.check_tool_call(tool_name, tool_args)
        if not gate_result.allow:
            return self._failure(
                tool_call_id,
                tool_name,
                f"[工具调用被拒绝] {gate_result.reason}",
                started_at,
            )

        policy_result = validate_tool_args(tool_name, tool_args)
        if not policy_result.valid:
            return self._failure(
                tool_call_id,
                tool_name,
                f"[参数错误] {policy_result.error_message}",
                started_at,
            )

        try:
            async with asyncio.timeout(self.timeout_seconds):
                value = await tool.ainvoke(tool_args)
        except TimeoutError:
            return self._failure(
                tool_call_id,
                tool_name,
                f"[工具执行失败] {tool_name}: timeout",
                started_at,
            )
        except Exception as error:
            return self._failure(
                tool_call_id,
                tool_name,
                f"[工具执行失败] {tool_name}: {type(error).__name__}: {str(error)[:150]}",
                started_at,
            )

        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=_result_text(value),
            status="completed",
            duration_ms=(perf_counter() - started_at) * 1000,
        )

    @staticmethod
    def _failure(
        tool_call_id: str,
        tool_name: str,
        content: str,
        started_at: float,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=content,
            status="failed",
            duration_ms=(perf_counter() - started_at) * 1000,
        )
