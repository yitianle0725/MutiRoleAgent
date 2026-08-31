"""Native Runtime 的模型流、工具循环和思维链隔离测试。"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool

from runtime.context import RunContext
from runtime.legacy_adapter import LegacyEventStreamAdapter
from runtime.native_runtime import NativeAgentRuntime
from runtime.request import RuntimeRequest
from runtime.think_filter import ThinkStreamFilter


class _FakeToolCallingModel:
    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def astream(self, messages):
        self.calls += 1
        if self.calls == 1:
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[{
                    "name": "lookup",
                    "args": '{"query":"Cyrene"}',
                    "id": "call-1",
                    "index": 0,
                    "type": "tool_call_chunk",
                }],
            )
            return
        yield AIMessageChunk(
            content="<thi",
            additional_kwargs={"reasoning_content": "private"},
        )
        yield AIMessageChunk(content="nk>hidden</think>答")
        yield AIMessageChunk(content="案")


@tool
async def lookup(query: str) -> str:
    """Return a deterministic test result."""

    return f"result:{query}"


def test_think_filter_handles_tags_split_across_chunks():
    filter_ = ThinkStreamFilter("leading-only")

    visible = filter_.push("  <thi")
    visible += filter_.push("nk>secret</thi")
    visible += filter_.push("nk>public")
    visible += filter_.flush()

    assert visible == "  public"
    assert filter_.take_thinking() == "secret"


def test_native_runtime_streams_answer_and_traces_tool_lifecycle():
    async def collect():
        runtime = NativeAgentRuntime(_FakeToolCallingModel(), [lookup])
        context = RunContext(session_id="session-1", run_id="run-1")
        request = RuntimeRequest(session_id="session-1", prompt="查询")
        return [event async for event in runtime.stream(request, context)]

    events = asyncio.run(collect())
    event_types = [event.type for event in events]

    assert event_types[0] == "run_started"
    assert event_types[-1] == "run_finished"
    assert events[0].data["runtime"] == "native"
    assert events[0].data["model"] == "_FakeToolCallingModel"
    assert events[0].data["tool_names"] == ["lookup"]
    assert events[0].data["system_prompt_hash"] == ""
    assert "tool_call_started" in event_types
    assert "tool_call_finished" in event_types
    assert "tool_result" in event_types
    text_deltas = [
        event.data["text"]
        for event in events
        if event.type == "text_delta"
    ]
    assert "".join(text_deltas) == "答案"
    assert text_deltas
    assert all("hidden" not in str(event.data) for event in events if event.visibility == "public")
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


def test_legacy_adapter_resets_provisional_text_for_tool_rounds():
    context = RunContext(session_id="session-1", run_id="run-1")
    adapter = LegacyEventStreamAdapter()

    events = []
    events.extend(adapter.feed(context.event("text_delta", {
        "message_id": "message-1",
        "text": "我先查询",
    })))
    events.extend(adapter.feed(context.event("text_finished", {
        "message_id": "message-1",
        "role": "activity",
        "text": "我先查询",
    })))

    assert [(event.type, event.data) for event in events] == [
        ("final_text", {"text": "我先查询", "delta": True}),
        ("process_text", {"text": "我先查询", "delta": False}),
        ("final_text", {"text": "", "delta": False}),
    ]
