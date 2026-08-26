"""L2 Memory 的离线回归评测。

覆盖检索阈值、无关记忆隔离、证据去重、生命周期和压缩触发条件。
不会读取或修改生产聊天数据库。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from memory.l2_memory import L2MemoryStore
from utils.path_tool import get_abs_path


CASES = [
    {
        "id": "anime_preference",
        "query": "给我推荐太空科幻动漫",
        "expected": "科幻动漫",
    },
    {
        "id": "novel_preference",
        "query": "想看家族修仙小说，有什么方向",
        "expected": "家族修仙",
    },
    {
        "id": "game_preference",
        "query": "帮我安排原神的探索内容",
        "expected": "原神",
    },
    {
        "id": "irrelevant_query",
        "query": "请解释 Python 的生成器",
        "expected": None,
    },
]


def _save_report(report: dict) -> Path:
    report_dir = Path(get_abs_path("evaluation/reports"))
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = report_dir / f"memory_offline_{timestamp}.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def run() -> dict:
    with TemporaryDirectory() as directory:
        store = L2MemoryStore(Path(directory) / "memory_eval.db")
        user_id = "memory-offline-eval"
        memories = [
            "我喜欢科幻动漫和太空题材作品。",
            "我喜欢家族修仙和群像小说。",
            "我经常玩原神，偏好探索与剧情内容。",
            "我不希望回答出现剧透。",
        ]
        for content in memories:
            store.add(user_id, content, source_quote=content, importance=0.7)

        retrieval_results: list[dict] = []
        for case in CASES:
            block = store.build_prompt_block(user_id, case["query"])
            passed = (
                not block
                if case["expected"] is None
                else case["expected"] in block
            )
            retrieval_results.append(
                {
                    "id": case["id"],
                    "passed": passed,
                    "prompt_block": block,
                }
            )

        duplicate_id = store.add(
            user_id,
            "我喜欢科幻动漫和太空题材作品。",
            source_quote="重复确认：我喜欢太空科幻。",
        )
        evidence_count = len(store.evidence(duplicate_id or 0))

        unique_topics = [
            "unique_memory_topic_alpha",
            "unique_memory_topic_bravo",
            "unique_memory_topic_charlie",
            "unique_memory_topic_delta",
            "unique_memory_topic_echo",
            "unique_memory_topic_foxtrot",
        ]
        for topic in unique_topics:
            store.add(user_id, topic)
        compression_trigger_ready = store.count_active_entries(user_id) >= 10

        passed_count = sum(item["passed"] for item in retrieval_results)
        report = {
            "evaluated_at": datetime.now().astimezone().isoformat(),
            "suite": "memory-offline-v1",
            "metrics": {
                "retrieval_pass_rate": round(passed_count / len(retrieval_results), 4),
                "relevant_recall": round(
                    sum(item["passed"] for item in retrieval_results[:-1])
                    / (len(retrieval_results) - 1),
                    4,
                ),
                "irrelevant_injection_blocked": retrieval_results[-1]["passed"],
                "duplicate_evidence_preserved": evidence_count >= 2,
                "compression_trigger_ready": compression_trigger_ready,
            },
            "cases": retrieval_results,
            "duplicate_evidence_count": evidence_count,
            "active_entries": store.count_active_entries(user_id),
        }
        report["passed"] = all(
            (
                report["metrics"]["retrieval_pass_rate"] == 1.0,
                report["metrics"]["duplicate_evidence_preserved"],
                report["metrics"]["compression_trigger_ready"],
            )
        )
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行 L2 Memory 离线评测")
    parser.add_argument("--output", help="可选报告输出路径")
    args = parser.parse_args()
    result = run()
    path = Path(args.output) if args.output else _save_report(result)
    if args.output:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": result["passed"], "report": str(path)}, ensure_ascii=False))
