"""Unit tests for evaluation baselines and CI regression checks."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.agent_metrics import performance_constraints, scenario_coverage
from eval.regression import check_baseline_cases, check_thresholds


def test_scenario_coverage_requires_all_five_categories() -> None:
    cases = [{"scenario": name} for name in ("agent", "memory", "tool", "safety", "performance")]
    coverage = scenario_coverage(cases)
    assert coverage["complete"] is True
    assert coverage["missing"] == []


def test_baseline_rejects_a_missing_category() -> None:
    with tempfile.TemporaryDirectory() as directory:
        baseline_path = Path(directory) / "baseline.json"
        baseline_path.write_text(
            json.dumps({"required_scenarios": ["agent", "memory"]}),
            encoding="utf-8",
        )
        result = check_baseline_cases([{"scenario": "agent"}], baseline_path)
    assert result["passed"] is False
    assert result["checks"][0]["missing"] == ["memory"]


def test_thresholds_reject_regressions() -> None:
    report = {
        "summary": {"e2e_success_rate": 0.5},
        "agent": {
            "agent_route_accuracy": {"accuracy": 0.7},
            "latency": {"p95_ms": 100},
        },
    }
    with tempfile.TemporaryDirectory() as directory:
        threshold_path = Path(directory) / "thresholds.json"
        threshold_path.write_text(
            json.dumps({"min_e2e_success_rate": 0.6, "min_agent_route_accuracy": 0.8}),
            encoding="utf-8",
        )
        result = check_thresholds(report, threshold_path)
    assert result["passed"] is False


def test_performance_constraints_reject_slow_result() -> None:
    cases = [{"id": 1, "scenario": "performance", "max_duration_ms": 100}]
    result = performance_constraints(cases, [{"id": 1, "duration_ms": 101}])
    assert result["passed"] is False
