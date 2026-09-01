"""证据充分性和最终答案的确定性校验。"""

from __future__ import annotations

import re

from .evidence import EvidenceLedger
from .tool_contracts import AnswerabilityDecision, ToolRequirement


_URL_PATTERN = re.compile(r"https?://[^\s\]\[<>()\"']+")
_MEASURE_PATTERN = re.compile(
    r"-?\d+(?:\.\d+)?\s*(?:°C|℃|元|%|公里|km|级|美元|人民币)", re.IGNORECASE,
)
_DATE_PATTERN = re.compile(r"20\d{2}(?:[-/.年]\d{1,2}){1,2}(?:日)?")


class AnswerabilityGate:
    def evaluate(
        self,
        requirement: ToolRequirement,
        ledger: EvidenceLedger,
        *,
        fallback_available: bool = False,
    ) -> AnswerabilityDecision:
        if not requirement.evidence_required:
            return AnswerabilityDecision("answerable", "该请求不强制要求外部证据")
        evidence = ledger.items
        if not evidence:
            status = "needs_fallback" if fallback_available else "not_answerable"
            return AnswerabilityDecision(status, "尚未取得通过验证的工具证据")

        available_fields = {
            key.lower()
            for item in evidence
            for key in item.fields
        }
        if ledger.urls():
            available_fields.add("url")
        if any(item.published_at for item in evidence):
            available_fields.add("published_at")
        missing = tuple(
            field for field in requirement.required_fields
            if field.lower() not in available_fields
        )
        if missing:
            return AnswerabilityDecision(
                "partially_answerable" if requirement.allow_partial_answer else "not_answerable",
                "证据缺少部分必需字段",
                missing_fields=missing,
                allowed_evidence_ids=tuple(item.evidence_id for item in evidence),
            )
        return AnswerabilityDecision(
            "answerable",
            "证据满足请求的最低要求",
            allowed_evidence_ids=tuple(item.evidence_id for item in evidence),
        )


class AnswerValidator:
    """阻止模型输出工具证据中不存在的链接。"""

    def validate(
        self,
        answer: str,
        requirement: ToolRequirement,
        ledger: EvidenceLedger,
    ) -> tuple[bool, tuple[str, ...]]:
        if not requirement.evidence_required:
            return True, ()
        errors: list[str] = []
        allowed_urls = ledger.urls()
        for raw_url in _URL_PATTERN.findall(answer):
            url = raw_url.rstrip(".,;，。；)")
            if url not in allowed_urls:
                errors.append(f"答案包含未被工具证据支持的 URL：{url}")
        evidence_text = " ".join(
            str(value)
            for item in ledger.items
            for value in (*item.fields.values(), item.published_at or "")
        )
        for fact in _MEASURE_PATTERN.findall(answer) + _DATE_PATTERN.findall(answer):
            if fact.replace(" ", "") not in evidence_text.replace(" ", ""):
                errors.append(f"答案包含未被工具证据支持的数值或日期：{fact}")
        if requirement.official_only and allowed_urls and not any(
            item.trust_level == "official" for item in ledger.items
        ):
            errors.append("请求要求官方来源，但没有官方证据")
        return not errors, tuple(errors)

    @staticmethod
    def safe_answer(decision: AnswerabilityDecision) -> str:
        if decision.missing_fields:
            fields = "、".join(decision.missing_fields)
            return f"我取得了部分结果，但缺少可验证的{fields}，因此无法给出确定答案。"
        return "我暂时没有取得足够且可验证的外部证据，因此不能可靠回答这个问题。"
