"""RAG 评测集的静态校验，防止没有标注的数据进入指标计算。"""

from __future__ import annotations

from collections import Counter
from typing import Any


RETRIEVAL_COLLECTIONS = {"faq", "worldbook", "anime"}


def validate_retrieval_cases(cases: list[dict[str, Any]]) -> list[str]:
    """返回标注问题列表；空列表表示评测集符合最低检索评测要求。"""
    issues: list[str] = []
    covered = Counter()
    for case in cases:
        if not case.get("retrieval_eval", False):
            continue
        collection = case.get("expected_route")
        relevant_texts = case.get("relevant_texts", [])
        if collection in RETRIEVAL_COLLECTIONS:
            if not relevant_texts:
                issues.append(f"case {case['id']} ({collection}) 缺少 relevant_texts")
            else:
                covered[collection] += 1

    for collection in RETRIEVAL_COLLECTIONS:
        if covered[collection] == 0:
            issues.append(f"collection {collection} 没有可计算检索指标的标注用例")
    return issues
