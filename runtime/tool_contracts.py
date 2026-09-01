"""Agent Runtime 的工具策略、执行结果和证据契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


ExecutionStatus = Literal[
    "completed", "timeout", "cancelled", "rejected", "invalid_arguments",
    "connection_error", "internal_error",
]
QualityStatus = Literal[
    "valid", "partial", "empty", "stale", "source_mismatch",
    "schema_invalid", "unverified",
]


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    """一次用户请求对外部证据的最低要求。"""

    evidence_required: bool = False
    freshness_required: bool = False
    official_only: bool = False
    required_fields: tuple[str, ...] = ()
    preferred_tools: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    max_tool_calls: int = 8
    max_attempts_per_tool: int = 2
    allow_partial_answer: bool = True
    reason: str = "普通知识请求"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Evidence:
    """可被最终答案引用的一条来源记录。"""

    evidence_id: str
    tool_name: str
    fields: dict[str, Any]
    source_url: str | None = None
    source_domain: str | None = None
    source_type: str = "tool_result"
    published_at: str | None = None
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    trust_level: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    """统一表达工具是否执行成功，以及结果是否足以使用。"""

    tool_call_id: str
    tool_name: str
    execution_status: ExecutionStatus
    quality_status: QualityStatus
    content: str
    data: Any = None
    evidence: tuple[Evidence, ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    fallback_required: bool = False
    attempt: int = 1
    duration_ms: float = 0.0

    @property
    def succeeded(self) -> bool:
        return self.execution_status == "completed"

    @property
    def usable(self) -> bool:
        return self.succeeded and self.quality_status in {"valid", "partial"}

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        result = asdict(self)
        if not include_content:
            result.pop("content", None)
            result.pop("data", None)
        return result


@dataclass(frozen=True, slots=True)
class AnswerabilityDecision:
    status: Literal[
        "answerable", "partially_answerable", "not_answerable",
        "needs_fallback", "needs_clarification",
    ]
    reason: str
    missing_fields: tuple[str, ...] = ()
    allowed_evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
