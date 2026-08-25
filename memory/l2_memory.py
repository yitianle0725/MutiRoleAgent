"""L2 长期事件记忆：证据、去重、冲突和生命周期。"""
from __future__ import annotations
import re, sqlite3, threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from utils.path_tool import get_abs_path

_TOKEN_RE = re.compile(r"[\\u4e00-\\u9fff]{2,}|[A-Za-z0-9_]{3,}")
_POSITIVE = ("喜欢", "偏好", "爱看", "想要", "记住", "我是", "以后")
_NEGATIVE = ("不喜欢", "讨厌", "不要", "不再", "不是")

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _tokens(text: str) -> set[str]:
    return {item.lower() for item in _TOKEN_RE.findall(text or "")}

def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / max(1, len(a | b))

@dataclass(frozen=True)
class MemoryItem:
    id: int
    user_id: str
    content: str
    status: str
    confidence: float
    access_count: int
    last_accessed_at: str

class L2MemoryStore:
    """SQLite L2 记忆库，保存长期事实及其来源证据。"""
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = str(db_path or get_abs_path("data/chat_history.db"))
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS l2_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, content TEXT NOT NULL, source_quote TEXT NOT NULL, source_session_id TEXT, status TEXT NOT NULL DEFAULT 'active', confidence REAL NOT NULL DEFAULT 0.5, importance REAL NOT NULL DEFAULT 0.5, access_count INTEGER NOT NULL DEFAULT 0, last_accessed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, superseded_by INTEGER, conflict_ids TEXT NOT NULL DEFAULT '[]')")
            conn.execute("CREATE TABLE IF NOT EXISTS l2_memory_evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id INTEGER NOT NULL, quote TEXT NOT NULL, session_id TEXT, message_id TEXT, created_at TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS l2_memory_conflict (id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id INTEGER NOT NULL, other_memory_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', reason TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(memory_id, other_memory_id))")

    @staticmethod
    def _contradicts(left: str, right: str) -> bool:
        return any((a in left and b in right) or (a in right and b in left) for a in _POSITIVE for b in _NEGATIVE)

    def add(self, user_id: str, content: str, *, source_quote: str | None = None, session_id: str | None = None, confidence: float = 0.7, importance: float = 0.5) -> int | None:
        content = (content or "").strip()
        if not user_id or not content:
            return None
        now, quote = _now(), (source_quote or content).strip()
        with self._lock, self._connection() as conn:
            rows = conn.execute("SELECT * FROM l2_memory WHERE user_id=? AND status IN ('active','aging')", (user_id,)).fetchall()
            conflict_ids: list[int] = []
            for row in rows:
                similarity = _similarity(content, row["content"])
                if similarity >= 0.72:
                    conn.execute("UPDATE l2_memory SET access_count=access_count+1, updated_at=? WHERE id=?", (now, row["id"]))
                    conn.execute("INSERT INTO l2_memory_evidence(memory_id,quote,session_id,created_at) VALUES(?,?,?,?)", (row["id"], quote, session_id, now))
                    return int(row["id"])
                if similarity >= 0.25 and self._contradicts(content, row["content"]):
                    conflict_ids.append(int(row["id"]))
            cursor = conn.execute("INSERT INTO l2_memory(user_id,content,source_quote,source_session_id,confidence,importance,last_accessed_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (user_id, content, quote, session_id, max(0,min(1,confidence)), max(0,min(1,importance)), now, now, now))
            memory_id = int(cursor.lastrowid)
            conn.execute("INSERT INTO l2_memory_evidence(memory_id,quote,session_id,created_at) VALUES(?,?,?,?)", (memory_id, quote, session_id, now))
            for other_id in conflict_ids:
                conn.execute("INSERT OR IGNORE INTO l2_memory_conflict(memory_id,other_memory_id,reason,created_at) VALUES(?,?,?,?)", (memory_id, other_id, "共享主题但正负表述冲突", now))
                conn.execute("INSERT OR IGNORE INTO l2_memory_conflict(memory_id,other_memory_id,reason,created_at) VALUES(?,?,?,?)", (other_id, memory_id, "共享主题但正负表述冲突", now))
            return memory_id

    def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        with self._lock, self._connection() as conn:
            rows = conn.execute("SELECT * FROM l2_memory WHERE user_id=? AND status IN ('active','aging')", (user_id,)).fetchall()
            ranked = sorted(rows, key=lambda row: _similarity(query, row["content"]) * row["confidence"] * (1 + min(row["importance"], 1)), reverse=True)[:limit]
            now = _now()
            for row in ranked:
                conn.execute("UPDATE l2_memory SET access_count=access_count+1,last_accessed_at=? WHERE id=?", (now, row["id"]))
            return [MemoryItem(row["id"], row["user_id"], row["content"], row["status"], row["confidence"], row["access_count"] + 1, now) for row in ranked]

    def maintain_lifecycle(self, aging_days: int = 30, archive_days: int = 180) -> dict[str, int]:
        now = datetime.now(timezone.utc); changed = {"aging": 0, "archived": 0}
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT id,status,last_accessed_at,importance FROM l2_memory WHERE status IN ('active','aging')").fetchall()
            for row in rows:
                try: days = (now - datetime.fromisoformat(row["last_accessed_at"])).days
                except (TypeError, ValueError): days = 0
                target = "archived" if days >= archive_days and row["importance"] < 0.8 else "aging" if days >= aging_days else "active"
                if target != row["status"]:
                    conn.execute("UPDATE l2_memory SET status=?,updated_at=? WHERE id=?", (target, _now(), row["id"])); changed[target] += 1
        return changed

    def evidence(self, memory_id: int) -> list[dict]:
        with self._connection() as conn:
            return [dict(row) for row in conn.execute("SELECT id,quote,session_id,message_id,created_at FROM l2_memory_evidence WHERE memory_id=? ORDER BY created_at", (memory_id,)).fetchall()]

    def list_conflicts(self, user_id: str, status: str = "candidate") -> list[dict]:
        """列出待人工或 LLM 判断的冲突，不自动覆盖任何一条记忆。"""
        with self._connection() as conn:
            rows = conn.execute("""
                SELECT c.id, c.memory_id, c.other_memory_id, c.status, c.reason,
                       m.content AS content, o.content AS other_content
                FROM l2_memory_conflict c
                JOIN l2_memory m ON m.id=c.memory_id
                JOIN l2_memory o ON o.id=c.other_memory_id
                WHERE m.user_id=? AND c.status=?
                ORDER BY c.created_at DESC
            """, (user_id, status)).fetchall()
            return [dict(row) for row in rows]

    def resolve_conflict(self, conflict_id: int, resolution: str, *, superseding_memory_id: int | None = None) -> None:
        """记录冲突处理结果；direct_conflict 时可将旧记忆标记为 superseded。"""
        allowed = {"dismissed", "resolved", "clarification_needed"}
        if resolution not in allowed:
            raise ValueError(f"resolution must be one of {sorted(allowed)}")
        with self._connection() as conn:
            row = conn.execute("SELECT memory_id FROM l2_memory_conflict WHERE id=?", (conflict_id,)).fetchone()
            if not row:
                return
            conn.execute("UPDATE l2_memory_conflict SET status=? WHERE id=?", (resolution, conflict_id))
            if resolution == "resolved" and superseding_memory_id:
                conn.execute("UPDATE l2_memory SET status='superseded', superseded_by=?, updated_at=? WHERE id=?", (superseding_memory_id, _now(), row["memory_id"]))

l2_memory_store = L2MemoryStore()

def capture_explicit_turn(user_id: str | None, session_id: str | None, user_text: str) -> int | None:
    """只捕获明确的长期表达，避免普通闲聊污染 L2。"""
    if not user_id or not user_text or not any(marker in user_text for marker in ("记住", "请记得", "我喜欢", "我偏好", "以后", "我是")):
        return None
    return l2_memory_store.add(user_id, user_text, source_quote=user_text, session_id=session_id, confidence=0.85, importance=0.7)
