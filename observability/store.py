"""非阻塞的 Agent 监控数据存储。"""

from __future__ import annotations

import json
import math
import queue
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.path_tool import get_abs_path
from utils.logger_handler import logger


class MonitorStore:
    """将每轮追踪数据交给后台线程写入 SQLite。

    Agent 主链路只执行 ``put_nowait``，不会因为磁盘 I/O 阻塞事件循环。
    """

    def __init__(self, db_path: Path | None = None) -> None:
        default_path = Path(get_abs_path("data/agent_monitor.db"))
        self._db_path = db_path or default_path
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=1000)
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def enqueue_turn(self, record: dict[str, Any]) -> None:
        """排队保存一轮数据；队列已满时丢弃最旧之外的新监控数据。"""
        self._ensure_worker()
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            logger.warning("[MonitorStore] 监控队列已满，已丢弃本轮记录")

    def close(self) -> None:
        """停止后台写线程，主要供测试和应用关闭时使用。"""
        worker = self._worker
        if worker is None or not worker.is_alive():
            return
        self._queue.put(None)
        worker.join(timeout=2)

    def list_turns(self, limit: int = 50) -> list[dict[str, Any]]:
        """读取最近的轮次摘要，供 API 或仪表盘展示。"""
        self._init_db()
        safe_limit = max(1, min(limit, 200))
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT trace_id, session_id, route, outcome, duration_ms,
                          ttft_ms, input_tokens, output_tokens, tool_calls,
                          error_type, created_at
                   FROM agent_turns
                   ORDER BY id DESC LIMIT ?""",
                (safe_limit,),
            ).fetchall()
        finally:
            conn.close()
        fields = (
            "trace_id", "session_id", "route", "outcome", "duration_ms",
            "ttft_ms", "input_tokens", "output_tokens", "tool_calls",
            "error_type", "created_at",
        )
        return [dict(zip(fields, row, strict=True)) for row in rows]

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """读取一轮摘要及其按时间排序的追踪事件。"""
        self._init_db()
        conn = sqlite3.connect(self._db_path)
        try:
            turn = conn.execute(
                "SELECT trace_id, session_id, route, outcome, duration_ms, "
                "ttft_ms, input_tokens, output_tokens, tool_calls, error_type, created_at "
                "FROM agent_turns WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
            if turn is None:
                return None
            rows = conn.execute(
                """SELECT event_index, step, elapsed_ms, detail
                   FROM agent_trace_events WHERE trace_id = ?
                   ORDER BY event_index""",
                (trace_id,),
            ).fetchall()
        finally:
            conn.close()
        fields = (
            "trace_id", "session_id", "route", "outcome", "duration_ms",
            "ttft_ms", "input_tokens", "output_tokens", "tool_calls",
            "error_type", "created_at",
        )
        result = dict(zip(fields, turn, strict=True))
        result["events"] = [
            {"index": row[0], "step": row[1], "elapsed_ms": row[2], "detail": row[3]}
            for row in rows
        ]
        return result

    def summary(self) -> dict[str, Any]:
        """汇总最近 1,000 轮的成功率和延迟分位数。"""
        self._init_db()
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT outcome, duration_ms, ttft_ms, input_tokens, output_tokens
                   FROM agent_turns ORDER BY id DESC LIMIT 1000"""
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return {"total_turns": 0, "success_rate": None, "p95_duration_ms": None}

        durations = sorted(row[1] for row in rows)
        p95_index = math.ceil(len(durations) * 0.95) - 1
        successes = sum(1 for row in rows if row[0] == "success")
        return {
            "total_turns": len(rows),
            "success_rate": round(successes / len(rows), 4),
            "p95_duration_ms": round(durations[p95_index], 2),
            "average_duration_ms": round(sum(durations) / len(durations), 2),
            "input_tokens": sum(row[3] for row in rows),
            "output_tokens": sum(row[4] for row in rows),
        }

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._write_loop,
                name="agent-monitor-writer",
                daemon=True,
            )
            self._worker.start()

    def _write_loop(self) -> None:
        try:
            self._init_db()
            while True:
                record = self._queue.get()
                if record is None:
                    return
                try:
                    self._write_turn(record)
                except Exception as error:
                    logger.warning(f"[MonitorStore] 保存监控记录失败: {error}")
        finally:
            self._worker = None

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    route TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    ttft_ms REAL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    error_type TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_trace_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    step TEXT NOT NULL,
                    elapsed_ms REAL NOT NULL,
                    detail TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_turns_created "
                "ON agent_turns(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_events_trace "
                "ON agent_trace_events(trace_id, event_index)"
            )
            conn.commit()
        finally:
            conn.close()

    def _write_turn(self, record: dict[str, Any]) -> None:
        created_at = datetime.now().isoformat(timespec="seconds")
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """INSERT OR REPLACE INTO agent_turns
                   (trace_id, session_id, route, outcome, duration_ms, ttft_ms,
                    input_tokens, output_tokens, tool_calls, error_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["trace_id"], record["session_id"], record["route"],
                    record["outcome"], record["duration_ms"], record.get("ttft_ms"),
                    record["input_tokens"], record["output_tokens"],
                    record["tool_calls"], record.get("error_type", ""), created_at,
                ),
            )
            conn.execute(
                "DELETE FROM agent_trace_events WHERE trace_id = ?",
                (record["trace_id"],),
            )
            conn.executemany(
                """INSERT INTO agent_trace_events
                   (trace_id, event_index, step, elapsed_ms, detail)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        record["trace_id"], event["index"], event["step"],
                        event["elapsed_ms"], json.dumps(event["detail"], ensure_ascii=False),
                    )
                    for event in record.get("events", [])
                ],
            )
            conn.commit()
        finally:
            conn.close()


monitor_store = MonitorStore()
