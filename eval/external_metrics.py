"""Optional adapters for ranx and RAGAS with lazy imports."""

from __future__ import annotations

from typing import Any


def build_ranx_inputs(cases: list[dict], retrieved: dict[str, list[str]]) -> tuple[dict, dict]:
    """Build qrels and ranked runs from cases with relevance annotations."""
    qrels: dict[str, dict[str, int]] = {}
    run: dict[str, dict[str, float]] = {}
    for case in cases:
        relevant = case.get("relevant_texts") or []
        if not relevant:
            continue
        case_id = str(case["id"])
        grades = case.get("relevance_grades") or {}
        qrels[case_id] = {str(doc): int(grades.get(doc, 1)) for doc in relevant}
        run[case_id] = {
            str(doc): 1.0 / (index + 1)
            for index, doc in enumerate(retrieved.get(case_id, []))
        }
    return qrels, run


def score_with_ranx(qrels: dict, run: dict, metrics: list[str] | None = None) -> dict[str, float]:
    """Calculate ranking metrics with ranx, with a clear optional install hint."""
    try:
        from ranx import Qrels, Run, evaluate
    except ImportError as exc:
        raise RuntimeError("Install optional dependency with: pip install ranx") from exc
    values = evaluate(Qrels(qrels), Run(run), metrics or ["recall@3", "precision@3", "mrr", "ndcg@3"])
    return {name: float(value) for name, value in values.items()}


async def score_with_ragas(samples: list[dict], llm: Any, embeddings: Any = None) -> dict:
    """Run RAGAS with a caller-provided judge model and credentials."""
    try:
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics import AnswerRelevancy, ContextRelevance, Faithfulness
    except ImportError as exc:
        raise RuntimeError("Install optional dependency with: pip install ragas") from exc
    dataset = EvaluationDataset.from_list(samples)
    kwargs = {"llm": llm}
    if embeddings is not None:
        kwargs["embeddings"] = embeddings
    result = evaluate(dataset, metrics=[Faithfulness(), AnswerRelevancy(), ContextRelevance()], **kwargs)
    return dict(result)
