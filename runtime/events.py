"""Agent Runtime 的统一事件协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


EventVisibility = Literal["public", "debug", "private"]
RunEventType = Literal[
    "run_started",
    "round_started",
    "round_finished",
    "model_started",
    "model_finished",
    "activity_updated",
    "reasoning_started",
    "reasoning_delta",
    "reasoning_finished",
    "text_started",
    "text_delta",
    "text_finished",
    "tool_call_started",
    "tool_args_delta",
    "tool_call_finished",
    "tool_result",
    "structured_data",
    "usage_updated",
    "checkpoint_saved",
    "run_finished",
    "run_failed",
]


def utc_now_iso() -> str:
    """返回适合持久化和跨语言传输的 UTC 时间。"""

    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class RunEvent:
    """Runtime、持久层和传输层共同消费的一条规范化事件。"""

    type: RunEventType
    run_id: str
    sequence: int
    data: dict[str, Any] = field(default_factory=dict)
    visibility: EventVisibility = "public"
    timestamp: str = field(default_factory=utc_now_iso)
    version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "type": self.type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "visibility": self.visibility,
            "data": dict(self.data),
        }
