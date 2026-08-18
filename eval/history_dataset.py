"""Load real conversations from the project's SQLite chat history."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def load_history_pairs(db_path: str | Path, limit: int | None = None) -> list[dict]:
    """Return user/assistant pairs in chronological order.

    Incomplete turns are kept with an empty answer so failures are visible in
    the report instead of being silently discarded.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT session_id, role, content, created_at, id "
            "FROM chat_history ORDER BY created_at ASC, id ASC"
        ).fetchall()
    finally:
        conn.close()

    pairs: list[dict] = []
    pending: dict[str, dict] = {}
    for session_id, role, content, created_at, row_id in rows:
        if role == "user":
            if session_id in pending:
                pairs.append(pending.pop(session_id))
            pending[session_id] = {
                "id": f"history-{row_id}",
                "session_id": session_id,
                "query": content or "",
                "answer": "",
                "created_at": created_at,
            }
        elif role == "assistant" and session_id in pending:
            item = pending.pop(session_id)
            item["answer"] = content or ""
            item["answer_created_at"] = created_at
            pairs.append(item)
    pairs.extend(pending.values())
    pairs.sort(key=lambda item: item["id"])
    return pairs[-limit:] if limit else pairs
