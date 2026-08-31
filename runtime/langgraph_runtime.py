"""现有 LangGraph Agent 到统一 Runtime 协议的迁移适配器。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from orchestration.session_runner import SessionAgentRunner

from .context import RunContext
from .events import RunEvent
from .legacy_adapter import harness_to_run_event
from .request import RuntimeRequest
from .settlement import RunSettlementGate, RunTerminalResult


class LangGraphRuntimeAdapter:
    """在不复制 LangGraph 循环的前提下输出规范化 Runtime 事件。"""

    def __init__(self, runner: SessionAgentRunner) -> None:
        self._runner = runner

    async def stream(
        self,
        request: RuntimeRequest,
        context: RunContext,
    ) -> AsyncIterator[RunEvent]:
        settlement = RunSettlementGate()
        text_started = False
        yield context.event(
            "run_started",
            {"session_id": context.session_id, "runtime": "langgraph"},
        )

        try:
            async for legacy_event in self._runner.stream(
                request.session_id,
                request.prompt,
                user_id=request.user_id,
                persona=request.persona,
                run_id=context.run_id,
                runtime_context=str(request.metadata.get("runtime_context", "")),
            ):
                if context.cancelled:
                    break

                if legacy_event.type == "final_text" and not text_started:
                    text_started = True
                    yield context.event("text_started")
                event = harness_to_run_event(legacy_event, context)
                if event is None:
                    continue
                yield event

            if text_started:
                yield context.event("text_finished")

            status = "cancelled" if context.cancelled else "completed"
            terminal = RunTerminalResult(status=status)
            if settlement.try_settle(terminal):
                yield context.event("run_finished", {"status": status})
        except TimeoutError as error:
            terminal = RunTerminalResult(status="timeout", error=str(error))
            if settlement.try_settle(terminal):
                yield context.event(
                    "run_failed",
                    {"status": "timeout", "error": str(error)},
                )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            terminal = RunTerminalResult(status="failed", error=message)
            if settlement.try_settle(terminal):
                yield context.event(
                    "run_failed",
                    {"status": "failed", "error": message},
                )
