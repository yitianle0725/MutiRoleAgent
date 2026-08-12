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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.react_agent import ReactAgent
from agent.stream_events import TextChunk, ToolEvent
from rag.rag_service import _route_query


def load_test_cases(path: str = None) -> list[dict]:
    """加载评测用例。"""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "test_cases.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def run_single_case(agent: ReactAgent, case: dict) -> dict:
    """对单个测试用例跑一次 agent，收集结果。"""
    query = case["query"]
    tools_called = []
    tool_outputs = []
    answer_parts = []

    try:
        async for event in agent.execute_stream_async(query):
            if isinstance(event, TextChunk):
                answer_parts.append(event.content)
            elif isinstance(event, ToolEvent):
                if event.phase == "start":
                    tools_called.append(event.tool_name)
                elif event.phase == "end":
                    tool_outputs.append(event.result_preview)
    except Exception as e:
        answer_parts.append(f"[ERROR: {e}]")

    return {
        "id": case["id"],
        "query": query,
        "answer": "".join(answer_parts),
        "tools_called": tools_called,
        "tool_outputs": tool_outputs,
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
            time.sleep(delay)

    return results


def run_and_evaluate():
    """同步入口：跑评测 + 计算 6 指标 + 保存报告。"""
    results = asyncio.run(run_all())

    cases = load_test_cases()

    # 检索评测用的 retriever 工厂
    from rag.vector_store import vector_store
    def retriever_fn(collection_name: str):
        return vector_store.get_retriever(collection_name)

    from eval.metrics import evaluate_all
    report = evaluate_all(cases, _route_query, retriever_fn, results, k=3)

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
    print(f"{'=' * 50}")

    return report


if __name__ == "__main__":
    run_and_evaluate()
