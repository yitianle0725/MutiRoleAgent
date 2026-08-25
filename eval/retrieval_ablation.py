"""比较 Dense/BM25 混合权重的离线脚本。

用法：python -m eval.retrieval_ablation
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.metrics import ndcg_at_k, precision_at_k, recall_at_k, mrr
from eval.runner import load_test_cases
from rag.vector_store import vector_store
from eval.report_time import report_timestamps


CONFIGS = {
    "dense_only": {"dense_weight": 1.0, "sparse_weight": 0.0},
    "balanced": {"dense_weight": 0.5, "sparse_weight": 0.5},
    "default": {"dense_weight": 0.7, "sparse_weight": 0.3},
    "sparse_heavy": {"dense_weight": 0.4, "sparse_weight": 0.6},
}


def run() -> dict[str, dict]:
    cases = [case for case in load_test_cases() if case.get("retrieval_eval")]
    report: dict[str, dict] = {}
    for name, config in CONFIGS.items():
        def retriever_factory(collection: str):
            store = vector_store._get_store(collection)
            bm25 = vector_store._get_bm25(collection)
            from rag.hybrid_retriever import HybridRetriever
            return HybridRetriever(collection, store, bm25, config=config)

        report[name] = {
            "config": config,
            "recall_at_3": recall_at_k(cases, retriever_factory, k=3)["recall"],
            "precision_at_3": precision_at_k(cases, retriever_factory, k=3)["precision"],
            "mrr": mrr(cases, retriever_factory)["mrr"],
            "ndcg_at_3": ndcg_at_k(cases, retriever_factory, k=3)["ndcg"],
        }
    return report


if __name__ == "__main__":
    output = run()
    output = {**report_timestamps(), **output}
    path = Path(__file__).with_name("retrieval_ablation_report.json")
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
