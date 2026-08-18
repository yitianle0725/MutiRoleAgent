"""Tests for the eight RAG evaluation metrics."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from eval.metrics import (
    answer_relevancy_score,
    context_recall_score,
    context_relevancy_score,
    faithfulness_score,
    ndcg_at_k,
    precision_at_k,
)


class FakeRetriever:
    def __init__(self, documents):
        self.documents = documents

    def invoke(self, query):
        return self.documents


def retriever_factory(collection):
    return FakeRetriever([
        SimpleNamespace(page_content="fact-a"),
        SimpleNamespace(page_content="noise"),
        SimpleNamespace(page_content="fact-b"),
    ])


def test_precision_and_ndcg_use_ranked_relevance() -> None:
    cases = [{
        "id": 1,
        "query": "question",
        "expected_route": "faq",
        "relevant_texts": ["fact-a", "fact-b"],
        "relevance_grades": {"fact-a": 3, "fact-b": 1},
    }]
    assert precision_at_k(cases, retriever_factory, k=3)["precision"] == 0.6667
    assert ndcg_at_k(cases, retriever_factory, k=3)["ndcg"] < 1.0


def test_generation_metrics_use_answer_and_context_evidence() -> None:
    cases = [{"id": 1, "query": "fact question", "key_facts": ["fact-a", "fact-b"], "relevant_texts": ["fact-a"]}]
    results = [{"id": 1, "answer": "fact-a", "contexts": ["fact-a", "fact-b"]}]
    assert faithfulness_score(cases, results)["score"] == 1.0
    assert answer_relevancy_score(cases, results)["score"] == 0.5
    assert context_relevancy_score(cases, results)["score"] == 1.0
    assert context_recall_score(cases, results)["score"] == 1.0


def test_generation_metrics_do_not_invent_context_scores() -> None:
    cases = [{"id": 1, "key_facts": ["fact-a"], "relevant_texts": ["fact-a"]}]
    results = [{"id": 1, "answer": "fact-a", "contexts": []}]
    assert faithfulness_score(cases, results)["score"] is None
    assert context_relevancy_score(cases, results)["score"] is None
    assert context_recall_score(cases, results)["score"] is None
