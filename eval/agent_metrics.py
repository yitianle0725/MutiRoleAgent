"""Agent 行为与性能评测指标。"""

from __future__ import annotations

import math
from typing import Any


def _cases_with(cases: list[dict], field: str) -> list[dict]:
    return [case for case in cases if field in case]


def route_accuracy(cases: list[dict], results: list[dict]) -> dict[str, Any]:
    """评估 Decision Engine 选择的 Chat / Agent 路径。"""
    expected_cases = _cases_with(cases, "expected_agent_route")
    result_by_id = {result["id"]: result for result in results}
    details = []
    for case in expected_cases:
        actual = result_by_id.get(case["id"], {}).get("agent_route", "unknown")
        expected = case["expected_agent_route"]
        details.append({"id": case["id"], "expected": expected, "actual": actual, "hit": actual == expected})
    correct = sum(item["hit"] for item in details)
    return {
        "accuracy": round(correct / len(details), 4) if details else None,
        "total": len(details),
        "details": details,
    }


def tool_constraints(cases: list[dict], results: list[dict]) -> dict[str, Any]:
    """检查必调工具和禁用工具。"""
    result_by_id = {result["id"]: result for result in results}
    details = []
    for case in cases:
        required = set(case.get("expected_tools", []))
        forbidden = set(case.get("forbidden_tools", []))
        if not required and not forbidden:
            continue
        actual = set(result_by_id.get(case["id"], {}).get("tools_called", []))
        hit = required.issubset(actual) and not forbidden.intersection(actual)
        details.append({
            "id": case["id"], "required": sorted(required), "forbidden": sorted(forbidden),
            "actual": sorted(actual), "hit": hit,
        })
    correct = sum(item["hit"] for item in details)
    return {"accuracy": round(correct / len(details), 4) if details else None, "total": len(details), "details": details}


def memory_accuracy(cases: list[dict], results: list[dict]) -> dict[str, Any]:
    """检查多轮场景的最终回答是否包含约定记忆事实。"""
    result_by_id = {result["id"]: result for result in results}
    details = []
    for case in _cases_with(cases, "memory_facts"):
        answer = result_by_id.get(case["id"], {}).get("answer", "")
        facts = case["memory_facts"]
        missing = [fact for fact in facts if fact not in answer]
        details.append({"id": case["id"], "missing_facts": missing, "hit": not missing})
    correct = sum(item["hit"] for item in details)
    return {"accuracy": round(correct / len(details), 4) if details else None, "total": len(details), "details": details}


def latency_metrics(results: list[dict]) -> dict[str, Any]:
    """计算端到端延迟的平均值和 P95。"""
    durations = sorted(result["duration_ms"] for result in results if result.get("duration_ms") is not None)
    if not durations:
        return {"count": 0, "average_ms": None, "p95_ms": None}
    # Nearest-rank P95, which is less surprising for small evaluation sets.
    index = math.ceil(len(durations) * 0.95) - 1
    return {
        "count": len(durations),
        "average_ms": round(sum(durations) / len(durations), 2),
        "p95_ms": round(durations[index], 2),
    }


def scenario_coverage(cases: list[dict]) -> dict[str, Any]:
    """统计 Agent 评测的五类场景是否齐全。"""
    required = {"agent", "memory", "tool", "safety", "performance"}
    actual = {case.get("scenario") for case in cases}
    missing = sorted(required - actual)
    return {
        "required": sorted(required),
        "actual": sorted(item for item in actual if item),
        "missing": missing,
        "complete": not missing,
    }


def performance_constraints(cases: list[dict], results: list[dict]) -> dict[str, Any]:
    """检查标记为性能场景的端到端延迟上限。"""
    result_by_id = {result["id"]: result for result in results}
    details = []
    for case in cases:
        if case.get("scenario") != "performance":
            continue
        maximum = case.get("max_duration_ms")
        actual = result_by_id.get(case["id"], {}).get("duration_ms")
        hit = actual is not None and (maximum is None or actual <= maximum)
        details.append({"id": case["id"], "maximum_ms": maximum, "actual_ms": actual, "hit": hit})
    correct = sum(item["hit"] for item in details)
    return {
        "passed": correct == len(details),
        "total": len(details),
        "details": details,
    }


def evaluate_agent_behavior(cases: list[dict], results: list[dict]) -> dict[str, Any]:
    """汇总 Agent 专属行为、记忆和性能指标。"""
    return {
        "agent_route_accuracy": route_accuracy(cases, results),
        "tool_constraints": tool_constraints(cases, results),
        "memory_accuracy": memory_accuracy(cases, results),
        "latency": latency_metrics(results),
        "scenario_coverage": scenario_coverage(cases),
        "performance_constraints": performance_constraints(cases, results),
    }
