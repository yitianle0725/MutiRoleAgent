"""L2 长期事件记忆：证据、去重、冲突和生命周期。"""
from __future__ import annotations
import json, re, sqlite3, threading
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
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS l2_memory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, content TEXT NOT NULL, source_quote TEXT NOT NULL, source_session_id TEXT, status TEXT NOT NULL DEFAULT 'active', confidence REAL NOT NULL DEFAULT 0.5, importance REAL NOT NULL DEFAULT 0.5, access_count INTEGER NOT NULL DEFAULT 0, last_accessed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, superseded_by INTEGER, conflict_ids TEXT NOT NULL DEFAULT '[]')")
            conn.execute("CREATE TABLE IF NOT EXISTS l2_memory_evidence (id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id INTEGER NOT NULL, quote TEXT NOT NULL, session_id TEXT, message_id TEXT, created_at TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS l2_memory_conflict (id INTEGER PRIMARY KEY AUTOINCREMENT, memory_id INTEGER NOT NULL, other_memory_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', reason TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(memory_id, other_memory_id))")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(l2_memory)")}
            if "embedding" not in columns:
                conn.execute("ALTER TABLE l2_memory ADD COLUMN embedding TEXT")
            if "is_summary" not in columns:
                conn.execute("ALTER TABLE l2_memory ADD COLUMN is_summary INTEGER NOT NULL DEFAULT 0")
            if "sub_entry_ids" not in columns:
                conn.execute("ALTER TABLE l2_memory ADD COLUMN sub_entry_ids TEXT NOT NULL DEFAULT '[]'")
            for column, definition in (("activation", "REAL NOT NULL DEFAULT 0.0"), ("intrinsic_value", "REAL NOT NULL DEFAULT 0.5"), ("recent_hits", "TEXT NOT NULL DEFAULT '[]'")):
                if column not in columns:
                    conn.execute(f"ALTER TABLE l2_memory ADD COLUMN {column} {definition}")
            if "conflict_type" not in {row[1] for row in conn.execute("PRAGMA table_info(l2_memory_conflict)")}: 
                conn.execute("ALTER TABLE l2_memory_conflict ADD COLUMN conflict_type TEXT")

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
            vector = self._embed(content)
            if vector:
                conn.execute("UPDATE l2_memory SET embedding=? WHERE id=?", (json.dumps(vector), memory_id))
            conn.execute("INSERT INTO l2_memory_evidence(memory_id,quote,session_id,created_at) VALUES(?,?,?,?)", (memory_id, quote, session_id, now))
            for other_id in conflict_ids:
                conn.execute("INSERT OR IGNORE INTO l2_memory_conflict(memory_id,other_memory_id,reason,created_at) VALUES(?,?,?,?)", (memory_id, other_id, "共享主题但正负表述冲突", now))
                conn.execute("INSERT OR IGNORE INTO l2_memory_conflict(memory_id,other_memory_id,reason,created_at) VALUES(?,?,?,?)", (other_id, memory_id, "共享主题但正负表述冲突", now))
            return memory_id

    def candidate_conflicts(self, user_id: str, content: str) -> list[MemoryItem]:
        """规则只负责找候选，不直接决定冲突类型。"""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM l2_memory WHERE user_id=? AND status IN ('active','aging')", (user_id,)).fetchall()
            return [
                MemoryItem(row["id"], row["user_id"], row["content"], row["status"], row["confidence"], row["access_count"], row["last_accessed_at"] or "")
                for row in rows if _similarity(content, row["content"]) >= 0.25
            ]

    def mark_conflict(self, memory_id: int, other_memory_id: int, reason: str) -> int:
        with self._connection() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO l2_memory_conflict(memory_id,other_memory_id,reason,created_at) VALUES(?,?,?,?)", (memory_id, other_memory_id, reason, _now()))
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute("SELECT id FROM l2_memory_conflict WHERE memory_id=? AND other_memory_id=?", (memory_id, other_memory_id)).fetchone()
            return int(row["id"])

    def search(self, user_id: str, query: str, limit: int = 5) -> list[MemoryItem]:
        with self._lock, self._connection() as conn:
            rows = conn.execute("SELECT * FROM l2_memory WHERE user_id=? AND status IN ('active','aging')", (user_id,)).fetchall()
            query_vector = self._embed(query)
            ranked = sorted(rows, key=lambda row: self._rank_score(query, query_vector, row), reverse=True)[:limit]
            now = _now()
            for row in ranked:
                try:
                    hits = json.loads(row["recent_hits"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    hits = []
                hits = (hits + [now])[-20:]
                activation = min(1.0, float(row["activation"] or 0.0) * 0.8 + 0.2)
                conn.execute("UPDATE l2_memory SET access_count=access_count+1,last_accessed_at=?,activation=?,recent_hits=? WHERE id=?", (now, activation, json.dumps(hits), row["id"]))
            return [MemoryItem(row["id"], row["user_id"], row["content"], row["status"], row["confidence"], row["access_count"] + 1, now) for row in ranked]

    @staticmethod
    def _embed(text: str) -> list[float] | None:
        try:
            from model.embedding_provider import LocalONNXProvider
            return LocalONNXProvider().embed_query(text)
        except Exception:
            return None

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        import math
        denominator = math.sqrt(sum(x*x for x in left) * sum(y*y for y in right))
        return sum(x*y for x, y in zip(left, right)) / denominator if denominator else 0.0

    def _rank_score(self, query: str, query_vector: list[float] | None, row: sqlite3.Row) -> float:
        lexical = _similarity(query, row["content"])
        semantic = 0.0
        if query_vector and row["embedding"]:
            try:
                semantic = self._cosine(query_vector, json.loads(row["embedding"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        relevance = semantic if semantic else lexical
        try:
            age_days = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(row["last_accessed_at"])).days)
        except (TypeError, ValueError):
            age_days = 0
        recency = 1.0 / (1.0 + age_days / 30)
        activation = min(1.0, row["access_count"] / 10)
        return 0.45 * relevance + 0.2 * activation + 0.2 * min(1.0, row["importance"]) + 0.15 * recency

    def maintain_lifecycle(self, aging_days: int = 30, archive_days: int = 180) -> dict[str, int]:
        now = datetime.now(timezone.utc); changed = {"aging": 0, "archived": 0}
        with self._lock, self._connection() as conn:
            rows = conn.execute("SELECT id,status,last_accessed_at,importance,intrinsic_value,activation,access_count,recent_hits FROM l2_memory WHERE status IN ('active','aging')").fetchall()
            for row in rows:
                try: days = (now - datetime.fromisoformat(row["last_accessed_at"])).days
                except (TypeError, ValueError): days = 0
                try:
                    recent = json.loads(row["recent_hits"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    recent = []
                recent_signal = 1.0 if recent and (now - datetime.fromisoformat(recent[-1])).days < 14 else 0.0
                score = 0.30 * float(row["importance"] or 0) + 0.25 * float(row["intrinsic_value"] or 0) + 0.20 * float(row["activation"] or 0) + 0.15 * min(1.0, int(row["access_count"] or 0) / 10) + 0.10 * recent_signal
                target = "archived" if days >= archive_days and score < 0.35 else "aging" if days >= aging_days and score < 0.60 else "active"
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

    def set_conflict_type(self, memory_id: int, other_memory_id: int, conflict_type: str) -> None:
        if conflict_type not in CONFLICT_TYPES:
            conflict_type = "uncertain"
        with self._connection() as conn:
            conn.execute("UPDATE l2_memory_conflict SET conflict_type=? WHERE memory_id=? AND other_memory_id=?", (conflict_type, memory_id, other_memory_id))

l2_memory_store = L2MemoryStore()

CONFLICT_TYPES = {"unrelated", "context_difference", "preference_evolution", "direct_conflict", "uncertain"}

async def judge_memory_conflict(new_content: str, old_content: str) -> dict:
    """让 LLM 对规则发现的候选冲突做二次判断。"""
    from model.factory import decision_model
    prompt = f"""你是记忆冲突裁决器。规则已经发现两条可能相关的记忆。
新记忆：{new_content}
旧记忆：{old_content}
只返回 JSON：{{"type":"unrelated|context_difference|preference_evolution|direct_conflict|uncertain","should_remember":true或false,"confidence":0到1,"reason":"简短原因"}}。
不要把相似当成冲突；偏好随时间变化应归类 preference_evolution。"""
    try:
        response = await decision_model.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        result = json.loads(str(text).strip())
    except Exception:
        return {"type": "uncertain", "should_remember": True, "confidence": 0.0, "reason": "LLM 不可用，保留候选等待复核"}
    if result.get("type") not in CONFLICT_TYPES:
        result["type"] = "uncertain"
    result["should_remember"] = bool(result.get("should_remember", True))
    return result

async def capture_explicit_turn_async(user_id: str | None, session_id: str | None, user_text: str) -> int | None:
    """规则筛选长期表达，再由 LLM 决定是否值得写入 L2。"""
    if not user_id or not user_text or not any(marker in user_text for marker in ("记住", "请记得", "我喜欢", "我偏好", "以后", "我是")):
        return None
    candidates = l2_memory_store.candidate_conflicts(user_id, user_text)
    verdicts: list[tuple[MemoryItem, dict]] = []
    for candidate in candidates:
        verdict = await judge_memory_conflict(user_text, candidate.content)
        verdicts.append((candidate, verdict))
        if not verdict["should_remember"]:
            return None
    memory_id = l2_memory_store.add(user_id, user_text, source_quote=user_text, session_id=session_id, confidence=0.85, importance=0.7)
    if memory_id:
        for candidate, verdict in verdicts:
            l2_memory_store.set_conflict_type(memory_id, candidate.id, verdict["type"])
    return memory_id

async def compress_similar_memories(user_id: str, threshold: float = 0.65, limit: int = 30) -> int:
    """将相似 L2 合并成一条 Memory Summary，原始记忆保留为 merged。"""
    from model.factory import decision_model
    with l2_memory_store._connection() as conn:
        rows = conn.execute("SELECT * FROM l2_memory WHERE user_id=? AND status IN ('active','aging') AND is_summary=0 ORDER BY created_at LIMIT ?", (user_id, limit)).fetchall()
    groups: list[list] = []
    for row in rows:
        group = next((g for g in groups if _similarity(row["content"], g[0]["content"]) >= threshold), None)
        if group is None:
            groups.append([row])
        else:
            group.append(row)
    compressed = 0
    for group in groups:
        if len(group) < 2:
            continue
        prompt = "把以下多条长期经历压缩成一条稳定、不过度推断的 Memory Summary，只返回一句中文：\n" + "\n".join(f"- {row['content']}" for row in group)
        try:
            response = await decision_model.ainvoke(prompt)
            summary = str(getattr(response, "content", response)).strip()
        except Exception:
            summary = "；".join(row["content"] for row in group)
        summary_id = l2_memory_store.add(user_id, summary, source_quote="；".join(row["source_quote"] for row in group), confidence=max(float(row["confidence"]) for row in group), importance=max(float(row["importance"]) for row in group))
        if summary_id:
            with l2_memory_store._connection() as conn:
                ids = [int(row["id"]) for row in group]
                placeholders = ",".join("?" for _ in ids)
                conn.execute(f"UPDATE l2_memory SET status='merged', is_summary=0, sub_entry_ids=? WHERE id IN ({placeholders})", (json.dumps(ids), *ids))
                conn.execute("UPDATE l2_memory SET is_summary=1, sub_entry_ids=? WHERE id=?", (json.dumps(ids), summary_id))
            compressed += 1
    return compressed

def capture_explicit_turn(user_id: str | None, session_id: str | None, user_text: str) -> int | None:
    """只捕获明确的长期表达，避免普通闲聊污染 L2。"""
    if not user_id or not user_text or not any(marker in user_text for marker in ("记住", "请记得", "我喜欢", "我偏好", "以后", "我是")):
        return None
    return l2_memory_store.add(user_id, user_text, source_quote=user_text, session_id=session_id, confidence=0.85, importance=0.7)
