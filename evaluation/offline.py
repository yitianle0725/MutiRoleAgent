"""无需网络和 LLM 的基础评测器。

它负责验证路由、工具调用和事实保真等硬约束；主观答案质量可在 LangSmith
中追加 LLM-as-judge 评测，不让评测本身阻塞开发环境。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class EvaluationCase:
    id: str
    input: str
    expected_output: str = ""
    facts: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    route: str = "agent"
    tools_expected: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvaluationResult:
    case_id: str
    passed: bool
    scores: dict[str, float]
    failures: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationReport:
    dataset_version: str
    total: int
    passed: int
    score: float
    results: list[EvaluationResult]
    prompt_version: str = "v1"
    model: str = "unknown"
    code_version: str = "working-tree"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_case(case: EvaluationCase, *, answer: str, route: str | None = None, tools_used: list[str] | None = None) -> EvaluationResult:
    failures: list[str] = []
    answer_text = str(answer or "")
    scores: dict[str, float] = {}
    if case.expected_output:
        expected = case.expected_output.lower()
        scores["answer_contains_expected"] = 1.0 if expected in answer_text.lower() else 0.0
        if not scores["answer_contains_expected"]:
            failures.append("answer_missing_expected_text")
    else:
        scores["answer_contains_expected"] = 1.0
    if route is not None and case.route:
        scores["route_correct"] = 1.0 if route == case.route else 0.0
        if not scores["route_correct"]:
            failures.append(f"route_expected_{case.route}_got_{route}")
    else:
        scores["route_correct"] = 1.0
    used = set(tools_used or [])
    scores["tool_routing"] = 1.0 if set(case.tools_expected).issubset(used) else 0.0
    if scores["tool_routing"] == 0.0:
        failures.append("expected_tool_not_used")
    # AgentFactResult 的错误必须原样可见，防止角色层把失败改成成功。
    if case.metadata.get("must_preserve_errors"):
        missing = [error for error in case.metadata["must_preserve_errors"] if error not in answer_text]
        scores["fact_fidelity"] = 1.0 if not missing else 0.0
        if missing:
            failures.append("fact_error_not_preserved")
    else:
        scores["fact_fidelity"] = 1.0
    passed = not failures
    return EvaluationResult(case.id, passed, scores, failures)


def evaluate_dataset(cases: list[EvaluationCase], *, answers: dict[str, str] | None = None, dataset_version: str = "local-v1") -> EvaluationReport:
    answers = answers or {case.id: case.expected_output for case in cases}
    results = [evaluate_case(case, answer=answers.get(case.id, ""), route=case.route, tools_used=case.tools_expected) for case in cases]
    passed = sum(item.passed for item in results)
    return EvaluationReport(dataset_version, len(results), passed, round(passed / len(results), 4) if results else 0.0, results)


def load_dataset(path: str | Path) -> list[EvaluationCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvaluationCase(**item) for item in data]


def save_report(report: EvaluationReport, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
