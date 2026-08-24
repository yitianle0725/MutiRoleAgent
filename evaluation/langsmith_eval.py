"""离线评测入口；默认不访问 LangSmith，保证无网络也能运行。"""

from __future__ import annotations

import argparse
from pathlib import Path

from .offline import evaluate_dataset, load_dataset, save_report


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
    parser.add_argument("--dataset", default="evaluation/datasets/smoke.json")
    parser.add_argument("--output", default="data/evaluations/smoke-report.json")
    parser.add_argument("--langsmith", action="store_true", help="上传脱敏数据集；需要 LangSmith API Key")
    args = parser.parse_args()
    cases = load_dataset(args.dataset)
    if args.langsmith:
        upload_to_langsmith(cases, project="MutiRoleAgent", dataset_name=Path(args.dataset).stem)
    report = evaluate_dataset(cases)
    save_report(report, args.output)
    print(f"dataset={report.dataset_version} passed={report.passed}/{report.total} score={report.score:.3f}")
    print(f"report={Path(args.output)}")
    return 0 if report.score >= 0.8 else 1


if __name__ == "__main__":
    raise SystemExit(main())
