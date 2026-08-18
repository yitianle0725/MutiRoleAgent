"""Evaluate recorded agent conversations without making new LLM calls.

Usage: ``python -m eval.history_runner --limit 100``
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from eval.history_dataset import load_history_pairs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "chat_history.db"
DEFAULT_OUTPUT = ROOT / "eval" / "history_eval_report.json"


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text.lower()))


def evaluate_history(pairs: list[dict]) -> dict:
    details = []
    for pair in pairs:
        query_terms = _terms(pair["query"])
        answer_terms = _terms(pair["answer"])
        overlap = len(query_terms & answer_terms) / len(query_terms) if query_terms else 0.0
        details.append({
            **pair,
            "answer_length": len(pair["answer"]),
            "query_term_overlap": round(overlap, 4),
            "answered": bool(pair["answer"].strip()),
        })
    count = len(details)
    answered = sum(item["answered"] for item in details)
    return {
        "schema_version": 1,
        "source": "data/chat_history.db",
        "tooling": {
            "deterministic": True,
            "ranx": _ranx_available(),
            "ragas": _ragas_available(),
            "note": "RAGAS is optional and is not invoked without an explicit judge configuration.",
        },
        "summary": {
            "conversations": count,
            "answered_rate": round(answered / count, 4) if count else 0.0,
            "mean_query_term_overlap": round(
                sum(item["query_term_overlap"] for item in details) / count, 4
            ) if count else 0.0,
            "mean_answer_length": round(
                sum(item["answer_length"] for item in details) / count, 2
            ) if count else 0.0,
        },
        "details": details,
    }


def _ranx_available() -> bool:
    try:
        import ranx  # noqa: F401
    except ImportError:
        return False
    return True


def _ragas_available() -> bool:
    try:
        import ragas  # noqa: F401
    except ImportError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    report = evaluate_history(load_history_pairs(args.db, args.limit))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"History evaluation report: {args.output}")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
