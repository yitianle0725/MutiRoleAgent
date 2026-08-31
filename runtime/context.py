"""一次 Agent 运行共享的身份、序号和取消状态。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from .events import EventVisibility, RunEvent, RunEventType, utc_now_iso


@dataclass(slots=True)
class RunContext:
    """由最外层入口创建，并在整个调用链中保持不变。"""

    session_id: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    started_at: str = field(default_factory=utc_now_iso)
    _sequence: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.session_id = str(self.session_id or "default")
        self.run_id = str(self.run_id or uuid.uuid4().hex)
        self.thread_id = str(self.thread_id or self.session_id)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self) -> None:
        """请求协作式取消；具体模型和工具在安全边界检查该信号。"""

        self.cancel_event.set()

    def next_sequence(self) -> int:
        """分配严格递增、从 1 开始的运行内事件序号。"""

        self._sequence += 1
        return self._sequence

    def event(
        self,
        event_type: RunEventType,
        data: dict[str, Any] | None = None,
        *,
        visibility: EventVisibility = "public",
    ) -> RunEvent:
        """创建一条已经绑定 canonical run ID 的事件。"""

        return RunEvent(
            type=event_type,
            run_id=self.run_id,
            sequence=self.next_sequence(),
            data=data or {},
            visibility=visibility,
        )
