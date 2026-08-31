"""迁移期 HarnessEvent 与 RunEvent 的转换。"""

from __future__ import annotations

from agent.harness_events import HarnessEvent

from .context import RunContext
from .events import RunEvent


def harness_to_run_event(event: HarnessEvent, context: RunContext) -> RunEvent | None:
    """把现有前端事件转换为 Runtime v2 事件。"""

    data = dict(event.data)
    if event.type == "process_text":
        return context.event(
            "activity_updated",
            {"text": str(data.get("text", ""))},
        )
    if event.type == "tool_start":
        return context.event("tool_call_started", data)
    if event.type == "tool_end":
        return context.event("tool_call_finished", data)
    if event.type == "structured_data":
        return context.event("structured_data", data)
    if event.type == "final_text":
        return context.event("text_delta", {"text": str(data.get("text", ""))})
    return None


def run_to_harness_event(event: RunEvent) -> HarnessEvent | None:
    """把公共 Runtime 事件转换为当前 Web 前端仍使用的 v1 协议。"""

    data = dict(event.data)
    converted: HarnessEvent | None = None
    if event.type == "run_started":
        converted = HarnessEvent(type="run_start", data=data)
    elif event.type == "activity_updated":
        converted = HarnessEvent.process_text(str(data.get("text", "")), delta=True)
    elif event.type == "text_delta":
        converted = HarnessEvent.final_text(str(data.get("text", "")), delta=True)
    elif event.type == "tool_call_started":
        converted = HarnessEvent(type="tool_start", data=data)
    elif event.type == "tool_call_finished":
        converted = HarnessEvent(type="tool_end", data=data)
    elif event.type == "structured_data":
        converted = HarnessEvent(type="structured_data", data=data)
    elif event.type in {"run_finished", "run_failed"}:
        converted = HarnessEvent(type="run_end", data=data)

    if converted is None:
        return None
    return converted.bind(run_id=event.run_id, sequence=event.sequence)
