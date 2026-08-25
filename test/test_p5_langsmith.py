import json

from evaluation.offline import EvaluationCase, benchmark_report, compare_reports, evaluate_case, evaluate_dataset
from observability.langsmith_integration import graph_config_metadata, safe_metadata
from prompts.registry import PromptRegistry


def test_langsmith_metadata_is_safe():
    metadata = safe_metadata({"run_id": "r1", "session_id": "s1", "api_key": "secret", "full_text": "hidden"})
    assert metadata == {"run_id": "r1", "session_id": "s1"}
    assert graph_config_metadata(run_id="r1", session_id="s1")["run_id"] == "r1"


def test_offline_evaluation_preserves_quality_gates():
    case = EvaluationCase(id="x", input="搜索", expected_output="结果", tools_expected=["search"])
    result = evaluate_case(case, answer="结果", route="agent", tools_used=["search"])
    assert result.passed
    report = evaluate_dataset([case])
    assert report.score == 1.0


def test_prompt_registry_reads_version():
    registry = PromptRegistry("prompts/versions")
    assert "事实" in registry.get("roleplay", "v1")
    assert registry.metadata("roleplay", "v1")["version"] == "v1"


def test_benchmark_and_version_comparison_detect_regression():
    case = EvaluationCase(id="x", input="搜索", tools_expected=["search"])
    baseline = evaluate_dataset([case], dataset_version="a")
    candidate = evaluate_dataset([case], answers={"x": ""}, tools={"x": []}, dataset_version="b")
    comparison = compare_reports(baseline, candidate)
    assert comparison["metrics"]["tool_routing"]["delta"] < 0
    assert benchmark_report(baseline)["quality_gate"] is True
