"""事件驱动 Agent Runtime 的离线契约测试。"""

from __future__ import annotations

import asyncio

from agent.harness_events import HarnessEvent
from runtime.context import RunContext
from runtime.langgraph_runtime import LangGraphRuntimeAdapter
from runtime.legacy_adapter import run_to_harness_event
from runtime.request import RuntimeRequest
from runtime.settlement import RunSettlementGate, RunTerminalResult


class _RecordingRunner:
    def __init__(self) -> None:
        self.run_id = None

    async def stream(self, session_id, prompt, **kwargs):
        self.run_id = kwargs.get("run_id")
        yield HarnessEvent.tool_start(
            tool_call_id="call-1",
            tool_name="search_anime",
            tool_args={"query": prompt},
        )
        yield HarnessEvent.tool_end(
            tool_call_id="call-1",
            tool_name="search_anime",
            result_preview="完成",
        )
        yield HarnessEvent.final_text("回答", delta=True)


def test_run_context_assigns_canonical_id_and_monotonic_sequence():
    context = RunContext(session_id="session-1", run_id="run-1")

    first = context.event("run_started")
    second = context.event("text_delta", {"text": "你好"})

    assert first.run_id == second.run_id == "run-1"
    assert [first.sequence, second.sequence] == [1, 2]
    assert second.to_dict()["version"] == 2
    assert second.to_dict()["visibility"] == "public"
    assert second.to_dict()["timestamp"]


def test_settlement_gate_only_accepts_the_first_terminal_result():
    gate = RunSettlementGate()

    assert gate.try_settle(RunTerminalResult(status="completed")) is True
    assert gate.try_settle(RunTerminalResult(status="failed", error="late")) is False
    assert gate.result == RunTerminalResult(status="completed")


def test_langgraph_adapter_emits_v2_events_with_one_run_id():
    async def collect():
        runner = _RecordingRunner()
        runtime = LangGraphRuntimeAdapter(runner)
        context = RunContext(session_id="session-1", run_id="run-1")
        request = RuntimeRequest(session_id="session-1", prompt="推荐动漫")
        events = [event async for event in runtime.stream(request, context)]
        return runner, events

    runner, events = asyncio.run(collect())

    assert runner.run_id == "run-1"
    assert [event.type for event in events] == [
        "run_started",
        "tool_call_started",
        "tool_call_finished",
        "text_started",
        "text_delta",
        "text_finished",
        "run_finished",
    ]
    assert [event.sequence for event in events] == list(range(1, 8))
    assert {event.run_id for event in events} == {"run-1"}


def test_v2_text_delta_can_be_served_to_the_legacy_frontend():
    context = RunContext(session_id="session-1", run_id="run-1")
    event = context.event("text_delta", {"text": "增量"})

    legacy = run_to_harness_event(event)

    assert legacy is not None
    assert legacy.type == "final_text"
    assert legacy.data == {"text": "增量", "delta": True}
    assert legacy.run_id == "run-1"
    assert legacy.sequence == 1
