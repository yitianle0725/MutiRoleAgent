"""Agent 运行的 exactly-once 终态结算。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


TerminalStatus = Literal["completed", "failed", "cancelled", "timeout"]


@dataclass(frozen=True, slots=True)
class RunTerminalResult:
    status: TerminalStatus
    error: str = ""


class RunSettlementGate:
    """只接受第一次终态，避免完成、异常和取消分支重复结算。"""

    def __init__(self) -> None:
        self._result: RunTerminalResult | None = None

    @property
    def result(self) -> RunTerminalResult | None:
        return self._result

    @property
    def is_settled(self) -> bool:
        return self._result is not None

    def try_settle(self, result: RunTerminalResult) -> bool:
        if self._result is not None:
            return False
        self._result = result
        return True
