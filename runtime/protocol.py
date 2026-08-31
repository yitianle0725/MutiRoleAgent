"""可替换 Agent Runtime 的最小接口。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from .context import RunContext
from .events import RunEvent
from .request import RuntimeRequest


class AgentRuntime(Protocol):
    """Native Runtime 和迁移期适配器都必须遵循的接口。"""

    async def stream(
        self,
        request: RuntimeRequest,
        context: RunContext,
    ) -> AsyncIterator[RunEvent]: ...
