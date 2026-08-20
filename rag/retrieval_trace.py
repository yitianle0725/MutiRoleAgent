"""RAG 原始检索追踪存储，用于调试和离线评测。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.path_tool import get_abs_path


class RetrievalTraceStore:
    """将一次 RAG 检索的路由、候选和最终片段写入 SQLite。"""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or get_abs_path("db/rag_retrieval_traces.sqlite3")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS rag_retrieval_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    collections_json TEXT NOT NULL,
                    trace_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_trace_created ON rag_retrieval_traces(created_at)"
            )

    def save(self, query: str, collections: list[str], trace: dict[str, Any]) -> None:
        with sqlite3.connect(self._db_path) as connection:
            connection.execute(
                """INSERT INTO rag_retrieval_traces(query, collections_json, trace_json, created_at)
                   VALUES (?, ?, ?, ?)""",
                (query, json.dumps(collections, ensure_ascii=False),
                 json.dumps(trace, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )


retrieval_trace_store = RetrievalTraceStore()
