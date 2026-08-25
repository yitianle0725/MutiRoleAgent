"""离线评测入口；默认不访问 LangSmith，保证无网络也能运行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .offline import benchmark_report, compare_reports, evaluate_dataset, load_dataset, save_report
from eval.report_time import report_timestamps


def upload_to_langsmith(cases, *, project: str, dataset_name: str) -> str | None:
    """可选上传样本到 LangSmith；失败时返回 None，不影响本地评测。"""
    try:
        from langsmith import Client
        client = Client()
        dataset = client.create_dataset(dataset_name=dataset_name, description="MutiRoleAgent offline evaluation dataset")
        client.create_examples(
            inputs=[{"input": case.input} for case in cases],
            outputs=[{"expected_output": case.expected_output} for case in cases],
            dataset_id=dataset.id,
        )
        return str(dataset.id)
    except Exception as exc:
        print(f"LangSmith upload skipped: {type(exc).__name__}: {exc}")
        return None


def evaluate_with_langsmith(target, *, dataset: str, evaluators: list | None = None, experiment_prefix: str = "mutiroleagent"):
    """调用 LangSmith Evaluation API；target 接收单条 input 并返回 output。"""
    try:
        from langsmith import evaluate
        return evaluate(target, data=dataset, evaluators=evaluators or [], experiment_prefix=experiment_prefix)
    except Exception as exc:
        print(f"LangSmith evaluation skipped: {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="MutiRoleAgent offline evaluation")
    parser.add_argument("--dataset", default="evaluation/datasets/benchmark_v1.json")
    parser.add_argument("--output", default="evaluation/reports/benchmark_v1.json")
    parser.add_argument("--langsmith", action="store_true", help="上传脱敏数据集；需要 LangSmith API Key")
    parser.add_argument("--baseline", help="已有评测报告路径，用于 A/B 版本对比")
    parser.add_argument("--version", default="benchmark-v1", help="本次候选版本名称")
    parser.add_argument("--results", help="真实运行结果 JSON：包含 answers/routes/tools 三个按 case id 索引的对象")
    args = parser.parse_args()
    cases = load_dataset(args.dataset)
    if args.langsmith:
        upload_to_langsmith(cases, project="MutiRoleAgent", dataset_name=Path(args.dataset).stem)
    result_data: dict[str, object] = {}
    if args.results:
        result_data = json.loads(Path(args.results).read_text(encoding="utf-8"))
    report = evaluate_dataset(
        cases,
        answers=result_data.get("answers") if isinstance(result_data.get("answers"), dict) else None,
        routes=result_data.get("routes") if isinstance(result_data.get("routes"), dict) else None,
        tools=result_data.get("tools") if isinstance(result_data.get("tools"), dict) else None,
        dataset_version=args.version,
    )
    save_report(report, args.output)
    benchmark = benchmark_report(report)
    print(json.dumps(benchmark, ensure_ascii=False, indent=2))
    print(f"report={Path(args.output)}")
    if args.baseline:
        baseline_data = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        from .offline import EvaluationReport, EvaluationResult
        baseline = EvaluationReport(
            dataset_version=baseline_data["dataset_version"], total=baseline_data["total"],
            passed=baseline_data["passed"], score=baseline_data["score"],
            results=[EvaluationResult(**item) for item in baseline_data["results"]],
        )
        comparison = compare_reports(baseline, report)
        comparison.update(report_timestamps())
        comparison_path = Path(args.output).with_name(f"{Path(args.output).stem}-comparison.json")
        comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"comparison={comparison_path}")
        if any(value["delta"] < 0 for value in comparison["metrics"].values()):
            return 1
    return 0 if benchmark["quality_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
