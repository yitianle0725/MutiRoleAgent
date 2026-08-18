"""评测报告的阈值回归检查。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def check_thresholds(report: dict, threshold_path: Path) -> dict:
    """将报告与 JSON 阈值比较，返回可供 CI 使用的检查结果。"""
    if not threshold_path.exists():
        return {"passed": True, "checks": [], "reason": "未配置阈值"}

    thresholds = json.loads(threshold_path.read_text(encoding="utf-8"))
    values = {
        "min_e2e_success_rate": report["summary"]["e2e_success_rate"],
        "min_recall_at_k": report["summary"].get("recall_at_k"),
        "min_precision_at_k": report["summary"].get("precision_at_k"),
        "min_mrr": report["summary"].get("mrr"),
        "min_ndcg_at_k": report["summary"].get("ndcg_at_k"),
        "min_faithfulness": report["summary"].get("faithfulness"),
        "min_answer_relevancy": report["summary"].get("answer_relevancy"),
        "min_context_relevancy": report["summary"].get("context_relevancy"),
        "min_context_recall": report["summary"].get("context_recall"),
        "min_agent_route_accuracy": report["agent"]["agent_route_accuracy"]["accuracy"],
        "max_p95_latency_ms": report["agent"]["latency"]["p95_ms"],
    }
    checks = []
    for name, expected in thresholds.items():
        actual = values.get(name)
        if actual is None:
            continue
        passed = actual >= expected if name.startswith("min_") else actual <= expected
        checks.append({"name": name, "expected": expected, "actual": actual, "passed": passed})
    return {"passed": all(check["passed"] for check in checks), "checks": checks}


def check_baseline_cases(cases: list[dict[str, Any]], baseline_path: Path) -> dict:
    """验证评测集是否保留基线中要求的场景类型。"""
    if not baseline_path.exists():
        return {"passed": True, "checks": [], "reason": "baseline not configured"}

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    required = set(baseline.get("required_scenarios", []))
    actual = {case.get("scenario") for case in cases}
    missing = sorted(required - actual)
    check = {
        "name": "required_scenarios",
        "expected": sorted(required),
        "actual": sorted(item for item in actual if item),
        "passed": not missing,
    }
    if missing:
        check["missing"] = missing
    return {"passed": check["passed"], "checks": [check]}


def combine_regression_checks(*results: dict) -> dict:
    """合并基线和指标阈值的检查结果。"""
    checks = [check for result in results for check in result.get("checks", [])]
    return {"passed": all(check["passed"] for check in checks), "checks": checks}
