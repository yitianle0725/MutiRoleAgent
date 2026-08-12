"""
评测指标
========
Router Accuracy / Citation Validity / End-to-End Success Rate
"""

import json
import re
from typing import Any


# ==================== 1. Router Accuracy ====================

def router_accuracy(cases: list[dict], route_func) -> dict:
    """评估 RAG 路由准确率。

    直接调用 _route_query(query) 与 expected_route 比对。

    Returns:
        {"accuracy": float, "total": int, "details": [...]}
    """
    correct = 0
    details = []
    for c in cases:
        predicted = route_func(c["query"])
        expected = c.get("expected_route", "faq")
        # predicted 是 list，取第一个
        pred_first = predicted[0] if predicted else "unknown"
        hit = pred_first == expected
        if hit:
            correct += 1
        details.append({
            "id": c["id"],
            "query": c["query"][:40],
            "expected": expected,
            "predicted": pred_first,
            "hit": hit,
        })
    return {
        "accuracy": round(correct / len(cases), 4) if cases else 0,
        "total": len(cases),
        "correct": correct,
        "details": details,
    }


# ==================== 2. Citation Validity ====================

def _extract_facts(text: str) -> set[str]:
    """从文本中提取关键事实词（数字、专有名词、书名号内容）。"""
    facts = set()
    # 数字（评分/排名/话数）
    for m in re.finditer(r'\b\d+\.?\d*\b', text):
        facts.add(m.group())
    # 书名号内容
    for m in re.finditer(r'《(.+?)》', text):
        facts.add(m.group(1))
    # 中文专有名词（连续 2-6 个汉字）
    for m in re.finditer(r'[一-龥]{2,6}', text):
        facts.add(m.group())
    return facts


def citation_validity(cases: list[dict], run_results: list[dict]) -> dict:
    """评估引用有效性：回答中的关键事实是否来自工具数据。

    对每个 case，检查 key_facts 是否出现在 tool_outputs 或 answer 中。
    不要求精确子串匹配——模糊判断关键词覆盖。

    Returns:
        {"validity_rate": float, "total": int, "details": [...]}
    """
    total_facts = 0
    covered_facts = 0
    details = []

    for r in run_results:
        case = next((c for c in cases if c["id"] == r["id"]), None)
        if not case:
            continue
        key_facts = case.get("key_facts", [])
        if not key_facts:
            continue

        answer = r.get("answer", "")
        tool_outputs = " ".join(r.get("tool_outputs", []))

        fact_results = []
        for fact in key_facts:
            total_facts += 1
            in_answer = fact.lower() in answer.lower()
            in_tools = fact.lower() in tool_outputs.lower()
            covered = in_answer or in_tools
            if covered:
                covered_facts += 1
            fact_results.append({"fact": fact, "in_answer": in_answer, "covered": covered})

        details.append({
            "id": case["id"],
            "query": case["query"][:40],
            "facts": fact_results,
            "tools_called": r.get("tools_called", []),
        })

    return {
        "validity_rate": round(covered_facts / total_facts, 4) if total_facts else 0,
        "total_facts": total_facts,
        "covered_facts": covered_facts,
        "details": details,
    }


# ==================== 3. End-to-End Success Rate ====================

def e2e_success_rate(cases: list[dict], run_results: list[dict]) -> dict:
    """评估端到端成功率：工具调用 + 回答质量 + 关键事实覆盖。

    判定标准（三项全满足即成功）：
    1) 预期工具被调用（expected_tools ⊆ actual_tools）
    2) 回答非空且长度 >= min_answer_len
    3) 至少一半 key_facts 被覆盖

    Returns:
        {"success_rate": float, "total": int, "details": [...]}
    """
    success = 0
    details = []

    for r in run_results:
        case = next((c for c in cases if c["id"] == r["id"]), None)
        if not case:
            continue

        # 1) 工具调用检查
        expected_tools = set(case.get("expected_tools", []))
        actual_tools = set(r.get("tools_called", []))
        tools_ok = len(expected_tools) == 0 or expected_tools.issubset(actual_tools)

        # 2) 回答长度检查
        answer_len = len(r.get("answer", ""))
        min_len = case.get("min_answer_len", 10)
        answer_ok = answer_len >= min_len

        # 3) 关键事实检查
        key_facts = case.get("key_facts", [])
        answer = r.get("answer", "")
        tool_outputs = " ".join(r.get("tool_outputs", []))
        if key_facts:
            hits = sum(
                1 for f in key_facts
                if f.lower() in answer.lower() or f.lower() in tool_outputs.lower()
            )
            facts_ok = hits >= len(key_facts) / 2
        else:
            facts_ok = True  # 无事实要求的 case 跳过

        all_ok = tools_ok and answer_ok and facts_ok
        if all_ok:
            success += 1

        details.append({
            "id": case["id"],
            "query": case["query"][:40],
            "tools_ok": tools_ok,
            "answer_ok": answer_ok,
            "facts_ok": facts_ok,
            "success": all_ok,
            "reason": [] if all_ok else [
                *([] if tools_ok else [f"工具: 期望{expected_tools}, 实际{actual_tools}"]),
                *([] if answer_ok else [f"回答长度: {answer_len} < {min_len}"]),
                *([] if facts_ok else ["关键事实不足"]),
            ],
        })

    return {
        "success_rate": round(success / len(run_results), 4) if run_results else 0,
        "total": len(run_results),
        "success": success,
        "details": details,
    }


# ==================== 汇总 ====================

# ==================== 4. Recall@k ====================

def recall_at_k(cases: list[dict], retriever_func, k: int = 3) -> dict:
    """评估检索召回率。

    对每个 query 调 ChromaDB retriever，检查标注的 relevant_texts
    是否出现在检索结果的 page_content 中。

    Args:
        cases: 含 relevant_texts 字段的测试用例
        retriever_func: retriever_fn(collection_name) → ChromaDB retriever
        k: top-k 值

    Returns:
        {"recall": float, "total": int, "details": [...]}
    """
    total_relevant = 0
    total_hits = 0
    details = []

    for c in cases:
        relevant = c.get("relevant_texts", [])
        if not relevant:
            continue

        route = c.get("expected_route", "faq")
        collection_map = {"faq": "faq", "anime": "anime", "worldbook": "worldbook"}
        coll = collection_map.get(route, "faq")

        try:
            retriever = retriever_func(coll)
            docs = retriever.invoke(c["query"])[:k]
        except Exception:
            docs = []

        doc_texts = [d.page_content for d in docs]
        hits = 0
        for rt in relevant:
            if any(rt in dt for dt in doc_texts):
                hits += 1
                total_hits += 1
            total_relevant += 1

        details.append({
            "id": c["id"],
            "query": c["query"][:40],
            "relevant_count": len(relevant),
            "hits": hits,
            "retrieved_count": len(docs),
        })

    return {
        "recall": round(total_hits / total_relevant, 4) if total_relevant else 0,
        "total_relevant": total_relevant,
        "total_hits": total_hits,
        "k": k,
        "details": details,
    }


# ==================== 5. MRR (Mean Reciprocal Rank) ====================

def mrr(cases: list[dict], retriever_func) -> dict:
    """计算 Mean Reciprocal Rank。

    对每个 query，找到第一个相关文档的排名 rank，
    MRR = mean(1/rank)。无相关文档时该 query 贡献 0。

    Returns:
        {"mrr": float, "total": int, "details": [...]}
    """
    rr_values = []
    details = []

    for c in cases:
        relevant = c.get("relevant_texts", [])
        if not relevant:
            continue

        route = c.get("expected_route", "faq")
        collection_map = {"faq": "faq", "anime": "anime", "worldbook": "worldbook"}
        coll = collection_map.get(route, "faq")

        try:
            retriever = retriever_func(coll)
            docs = retriever.invoke(c["query"])
        except Exception:
            docs = []

        first_rank = 0
        for rank, doc in enumerate(docs, 1):
            if any(rt in doc.page_content for rt in relevant):
                first_rank = rank
                break

        rr = 1.0 / first_rank if first_rank > 0 else 0.0
        rr_values.append(rr)

        details.append({
            "id": c["id"],
            "query": c["query"][:40],
            "first_relevant_rank": first_rank,
            "rr": round(rr, 4),
        })

    return {
        "mrr": round(sum(rr_values) / len(rr_values), 4) if rr_values else 0,
        "total": len(rr_values),
        "details": details,
    }


# ==================== 6. Abstention Accuracy ====================

_ABSTENTION_MARKERS = [
    "不知道", "无法回答", "没有找到", "暂时无法",
    "我不清楚", "无法提供", "抱歉.*无法", "没有相关",
    "不太确定", "无法获取", "超出.*范围", "暂无",
]


def _is_abstention(answer: str) -> bool:
    """判断回答是否是"拒答"（含不知道/无法回答等标记）。"""
    import re
    answer_lower = answer.lower()
    for marker in _ABSTENTION_MARKERS:
        if re.search(marker, answer_lower):
            return True
    return len(answer.strip()) < 5


def abstention_accuracy(cases: list[dict], run_results: list[dict]) -> dict:
    """评估拒答准确率。

    should_abstain=true  → 期望 agent 说"不知道"
    should_abstain=false → 期望 agent 给出有效回答

    Returns:
        {"accuracy": float, "total": int, "details": [...]}
    """
    correct = 0
    total = 0
    details = []

    for r in run_results:
        case = next((c for c in cases if c["id"] == r["id"]), None)
        if case is None or "should_abstain" not in case:
            continue

        total += 1
        expected_abstain = case["should_abstain"]
        actual_abstain = _is_abstention(r.get("answer", ""))

        hit = expected_abstain == actual_abstain
        if hit:
            correct += 1

        details.append({
            "id": case["id"],
            "query": case["query"][:40],
            "expected_abstain": expected_abstain,
            "actual_abstain": actual_abstain,
            "hit": hit,
            "answer_preview": r.get("answer", "")[:80],
        })

    return {
        "accuracy": round(correct / total, 4) if total else 0,
        "total": total,
        "correct": correct,
        "details": details,
    }


# ==================== 汇总 ====================

def evaluate_all(cases: list[dict], route_func, retriever_func,
                 run_results: list[dict], k: int = 3) -> dict:
    """运行全部 6 个指标，输出汇总 JSON。"""
    router = router_accuracy(cases, route_func)
    recall = recall_at_k(cases, retriever_func, k=k)
    mrr_result = mrr(cases, retriever_func)
    citation = citation_validity(cases, run_results)
    abstain = abstention_accuracy(cases, run_results)
    e2e = e2e_success_rate(cases, run_results)

    return {
        "router_accuracy": router,
        "recall_at_k": recall,
        "mrr": mrr_result,
        "citation_validity": citation,
        "abstention_accuracy": abstain,
        "e2e_success_rate": e2e,
        "summary": {
            "router_accuracy": router["accuracy"],
            "recall_at_k": recall["recall"],
            "mrr": mrr_result["mrr"],
            "citation_validity": citation["validity_rate"],
            "abstention_accuracy": abstain["accuracy"],
            "e2e_success_rate": e2e["success_rate"],
            "test_cases": len(cases),
        },
    }
