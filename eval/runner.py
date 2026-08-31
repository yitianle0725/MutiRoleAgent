"""
评测执行器
==========
对测试集中的每个 query 跑 agent，收集工具调用和回答文本。
"""

import sys
import os
import json
import asyncio
import time
import random
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.react_agent import ReactAgent
from rag.rag_service import _route_query
from eval.agent_metrics import evaluate_agent_behavior
from eval.regression import check_baseline_cases, check_thresholds, combine_regression_checks
from eval.validate_dataset import validate_retrieval_cases
from eval.report_time import report_timestamps


def load_test_cases(path: str = None) -> list[dict]:
    """加载评测用例。"""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "test_cases.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def run_single_case(agent: ReactAgent, case: dict) -> dict:
    """对单个测试用例跑 agent，支持 ``turns`` 多轮场景。"""
    queries = case.get("turns") or [case["query"]]
    tools_called = []
    tool_outputs = []
    answer_parts: list[str] = []
    started_at = time.perf_counter()

    for query in queries:
        turn_answer: list[str] = []
        try:
            async for event in agent.execute_stream_async(query):
                if event.type == "final_text":
                    turn_answer.append(str(event.data.get("text", "")))
                elif event.type == "tool_start":
                    tools_called.append(str(event.data.get("tool_name", "")))
                elif event.type == "tool_end":
                    tool_outputs.append(str(event.data.get("result_preview", "")))
        except Exception as error:
            turn_answer.append(f"[ERROR: {error}]")
        answer_parts = turn_answer

    observation = agent.get_last_turn_observation()

    return {
        "id": case["id"],
        "query": queries[-1],
        "answer": "".join(answer_parts),
        "tools_called": tools_called,
        "tool_outputs": tool_outputs,
        "contexts": tool_outputs,
        "agent_route": observation["route"],
        "trace_id": observation["trace_id"],
        "outcome": observation["outcome"],
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }


async def run_all(session_prefix: str = "eval") -> list[dict]:
    """跑全部测试用例。

    每个 case 使用独立 session 避免历史污染。
    用例间间隔 2-4s 避免 API 限流。
    """
    cases = load_test_cases()
    print(f"评测用例: {len(cases)} 条\n")

    results = []
    for i, case in enumerate(cases):
        print(f"[{i + 1}/{len(cases)}] {case['query'][:50]}…", end=" ", flush=True)
        agent = ReactAgent(session_id=f"{session_prefix}_{case['id']}")
        await agent.init_agent()

        result = await run_single_case(agent, case)
        results.append(result)

        status = "✓" if result["answer"] else "✗"
        print(f"{status} (tools={result['tools_called']}, len={len(result['answer'])})")

        # 间隔避免限流
        if i < len(cases) - 1:
            delay = random.uniform(2.0, 4.0)
            await asyncio.sleep(delay)

    return results


def run_and_evaluate():
    """同步入口：跑评测 + 计算 6 指标 + 保存报告。"""
    results = asyncio.run(run_all())

    cases = load_test_cases()
    annotation_issues = validate_retrieval_cases(cases)
    if annotation_issues:
        raise ValueError("评测集标注不完整：\n- " + "\n- ".join(annotation_issues))

    # 检索评测用的 retriever 工厂
    from rag.vector_store import vector_store
    def retriever_fn(collection_name: str):
        return vector_store.get_retriever(collection_name)

    from eval.metrics import evaluate_all
    report = evaluate_all(cases, _route_query, retriever_fn, results, k=3)
    report["agent"] = evaluate_agent_behavior(cases, results)
    threshold_path = Path(__file__).with_name("thresholds.json")
    baseline_path = Path(__file__).with_name("baseline.json")
    baseline = check_baseline_cases(cases, baseline_path)
    thresholds = check_thresholds(report, threshold_path)
    performance = report["agent"]["performance_constraints"]
    performance_check = {
        "passed": performance["passed"],
        "checks": [
            {
                "name": "performance_constraints",
                "expected": "all performance cases within their limits",
                "actual": performance["total"] - sum(
                    item["hit"] for item in performance["details"]
                ),
                "passed": performance["passed"],
            }
        ],
    }
    report["regression"] = combine_regression_checks(
        baseline,
        thresholds,
        performance_check,
    )
    report.update(report_timestamps())

    # 保存报告
    output_path = os.path.join(os.path.dirname(__file__), "eval_report.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印摘要
    s = report["summary"]
    print(f"\n{'=' * 50}")
    print(f"评测报告: {output_path}")
    print(f"用例数: {s['test_cases']}")
    print(f"Router Accuracy:       {s['router_accuracy']:.2%}")
    print(f"Recall@3:              {s['recall_at_k']:.2%}")
    print(f"MRR:                   {s['mrr']:.2%}")
    print(f"Citation Validity:     {s['citation_validity']:.2%}")
    print(f"Abstention Accuracy:   {s['abstention_accuracy']:.2%}")
    print(f"E2E Success Rate:      {s['e2e_success_rate']:.2%}")
    latency = report["agent"]["latency"]
    print(f"Agent P95 Latency:     {latency['p95_ms']} ms")
    print(f"Regression Check:      {'PASS' if report['regression']['passed'] else 'FAIL'}")
    print(f"{'=' * 50}")

    return report


if __name__ == "__main__":
    evaluation_report = run_and_evaluate()
    raise SystemExit(0 if evaluation_report["regression"]["passed"] else 1)
