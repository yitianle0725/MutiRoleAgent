"""
SQLite 聊天记录持久化模块
=========================
提供对话历史的持久化存储，服务重启后历史不丢失。

表结构::

    chat_history
    ├── id          INTEGER PRIMARY KEY AUTOINCREMENT
    ├── session_id  TEXT NOT NULL        — 会话唯一标识
    ├── role        TEXT NOT NULL        — 'user' | 'assistant'
    ├── content     TEXT NOT NULL        — 消息正文
    └── created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP  — 写入时间

索引:
- ``idx_chat_session`` ON (session_id)             — 按会话快速查询
- ``idx_chat_session_time`` ON (session_id, created_at) — 按时间排序

使用方式::

    from memory.chat_db import chat_db

    chat_db.init_db()                              # 启动时建表
    chat_db.save_message("abc", "user", "你好")     # 保存用户消息
    chat_db.save_message("abc", "assistant", "你好")# 保存 AI 回复
    history = chat_db.get_history("abc")           # 查询会话历史
    chat_db.clear_session("abc")                   # 清空会话
"""

import json
import sqlite3
import threading
from datetime import datetime
from typing import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from utils.logger_handler import logger
from utils.path_tool import get_abs_path
from memory.persona_catalog import persona_catalog
from orchestration.models import SessionContext

# 数据库文件路径
DB_PATH = get_abs_path("data/chat_history.db")

# 单次查询最大返回条数
DEFAULT_LIMIT = 500


class ChatDB:
    """SQLite 聊天记录持久化存储。

    线程安全：每个方法独立获取连接，写操作自动 commit。
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._lock = threading.Lock()

    # ==================== 表初始化 ====================

    def init_db(self):
        """创建所有表及索引（幂等，已存在则跳过）。

        应在应用启动时调用一次，后续写操作不再需要。
        """
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                # ---- chat_history: 对话消息 ----
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chat_history (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id  TEXT    NOT NULL,
                        role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
                        content     TEXT    NOT NULL,
                        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chat_session
                    ON chat_history(session_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chat_session_time
                    ON chat_history(session_id, created_at)
                """)

                # ---- user_profile: 用户画像（L0 长期记忆） ----
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS user_profile (
                        user_id      TEXT PRIMARY KEY,
                        device_model TEXT DEFAULT '',
                        preferences  TEXT DEFAULT '{}',
                        issues_log   TEXT DEFAULT '[]',
                        extra        TEXT DEFAULT '{}',
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # ---- session_meta: 会话元数据（标题等） ----
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS session_meta (
                        session_id   TEXT PRIMARY KEY,
                        title        TEXT DEFAULT '',
                        user_id      TEXT DEFAULT '',
                        message_count INTEGER DEFAULT 0,
                        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_session_meta_user
                    ON session_meta(user_id)
                """)
                self._init_scoped_schema(conn)
                self._migrate_legacy_data(conn)
                conn.commit()
                logger.info(f"[ChatDB] 表初始化完成: {self._db_path}")
            finally:
                conn.close()

    @staticmethod
    def _init_scoped_schema(conn: sqlite3.Connection) -> None:
        """创建按 User、Persona、Session 分层的新数据表。"""
        conn.executescript("""
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS personas (
                persona_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                language TEXT DEFAULT '',
                occupation TEXT DEFAULT '',
                stable_interests TEXT DEFAULT '[]',
                preferences TEXT DEFAULT '{}',
                extra TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS user_persona_profiles (
                user_id TEXT NOT NULL,
                persona_id TEXT NOT NULL,
                preferred_address TEXT DEFAULT '',
                user_address_for_persona TEXT DEFAULT '',
                relationship_stage TEXT DEFAULT '',
                affinity REAL DEFAULT 0,
                shared_experiences TEXT DEFAULT '[]',
                preferences TEXT DEFAULT '{}',
                extra TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, persona_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (persona_id) REFERENCES personas(persona_id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                persona_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ('chat', 'work')),
                title TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                workspace TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (persona_id) REFERENCES personas(persona_id)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_user
            ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_persona
            ON sessions(user_id, persona_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_persona_mode
            ON sessions(user_id, persona_id, mode);

            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool', 'system')),
                content TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session_time
            ON messages(session_id, created_at, message_id);

            CREATE TABLE IF NOT EXISTS memories (
                memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL CHECK(scope IN ('user_global', 'user_persona', 'session')),
                user_id TEXT NOT NULL,
                persona_id TEXT,
                session_id TEXT,
                content TEXT NOT NULL,
                source_quote TEXT DEFAULT '',
                confidence REAL DEFAULT 0.5,
                importance REAL DEFAULT 0.5,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_memories_global
            ON memories(scope, user_id, status);
            CREATE INDEX IF NOT EXISTS idx_memories_persona
            ON memories(scope, user_id, persona_id, status);
            CREATE INDEX IF NOT EXISTS idx_memories_session
            ON memories(scope, session_id, status);
        """)

        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, display_name) VALUES('local_user', '本地用户')"
        )
        for persona in persona_catalog.list():
            conn.execute(
                """INSERT INTO personas
                   (persona_id, name, display_name, enabled)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(persona_id) DO UPDATE SET
                     name=excluded.name,
                     display_name=excluded.display_name,
                     enabled=1""",
                (persona.persona_id, persona.name, persona.display_name),
            )

    @staticmethod
    def _migrate_legacy_data(conn: sqlite3.Connection) -> None:
        """幂等迁移旧会话；原表保留作为回滚来源。"""
        rows = conn.execute(
            """SELECT ids.session_id,
                      COALESCE(NULLIF(meta.user_id, ''), 'local_user'),
                      COALESCE(NULLIF(meta.title, ''), '新会话'),
                      COALESCE(meta.message_count, 0),
                      meta.created_at,
                      meta.updated_at
               FROM (
                   SELECT session_id FROM session_meta
                   UNION
                   SELECT DISTINCT session_id FROM chat_history
               ) ids
               LEFT JOIN session_meta meta ON meta.session_id = ids.session_id"""
        ).fetchall()
        for session_id, user_id, title, count, created_at, updated_at in rows:
            conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
            conn.execute(
                """INSERT OR IGNORE INTO sessions
                   (session_id, user_id, persona_id, mode, title, message_count,
                    created_at, updated_at)
                   VALUES (?, ?, 'cyrene', 'chat', ?, ?,
                           COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))""",
                (session_id, user_id, title, count, created_at, updated_at),
            )
        conn.execute(
            """INSERT INTO messages(session_id, role, content, created_at)
               SELECT old.session_id, old.role, old.content, old.created_at
               FROM chat_history old
               WHERE NOT EXISTS (
                   SELECT 1 FROM messages current
                   WHERE current.session_id = old.session_id
               )"""
        )
        conn.execute(
            """UPDATE sessions SET message_count = (
                   SELECT COUNT(*) FROM messages
                   WHERE messages.session_id = sessions.session_id
               )"""
        )

    # ==================== 写入 ====================

    def save_message(self, session_id: str, role: str, content: str):
        """保存一条消息到持久化存储。

        Args:
            session_id: 会话唯一标识。
            role:       'user' 或 'assistant'。
            content:    消息文本内容。
        """
        if not content or not content.strip():
            return

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, role, content),
                )
                conn.execute(
                    """UPDATE sessions SET message_count = message_count + 1,
                       updated_at = CURRENT_TIMESTAMP WHERE session_id = ?""",
                    (session_id,),
                )
                conn.commit()
                logger.debug(
                    f"[ChatDB] 写入 {role}: session={session_id[:8]}… "
                    f"len={len(content)}"
                )
            finally:
                conn.close()

    def save_pair(self, session_id: str, user_msg: str, assistant_msg: str):
        """同时保存一对 user + assistant 消息（单事务）。"""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (?, 'user', ?)",
                    (session_id, user_msg),
                )
                conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (?, 'assistant', ?)",
                    (session_id, assistant_msg),
                )
                conn.execute(
                    """UPDATE sessions SET message_count = message_count + 2,
                       updated_at = CURRENT_TIMESTAMP WHERE session_id = ?""",
                    (session_id,),
                )
                conn.commit()
                logger.debug(
                    f"[ChatDB] 写入 pair: session={session_id[:8]}…"
                )
            finally:
                conn.close()

    # ==================== 查询 ====================

    def get_history(
        self, session_id: str, limit: int = DEFAULT_LIMIT
    ) -> list[BaseMessage]:
        """按时间顺序返回指定会话的消息历史（BaseMessage 格式）。

        Args:
            session_id: 会话唯一标识。
            limit:      最大返回条数。

        Returns:
            ``list[HumanMessage | AIMessage]``，与 session_store 格式兼容。
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT role, content FROM messages
                   WHERE session_id = ?
                   ORDER BY created_at ASC, message_id ASC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        finally:
            conn.close()

        messages: list[BaseMessage] = []
        for role, content in rows:
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        return messages

    def get_history_raw(
        self, session_id: str, limit: int = DEFAULT_LIMIT
    ) -> list[dict]:
        """按时间顺序返回指定会话的消息历史（原始 dict 格式，供 UI 展示）。

        Returns:
            ``[{"role": "user", "content": "…", "created_at": "…"}, …]``
        """
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT role, content, created_at FROM messages
                   WHERE session_id = ?
                   ORDER BY created_at ASC, message_id ASC
                   LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        finally:
            conn.close()

        return [
            {"role": role, "content": content, "created_at": created_at}
            for role, content, created_at in rows
        ]

    # ==================== 管理 ====================

    def clear_session(self, session_id: str):
        """清空指定会话的全部持久化记录（chat_history + session_meta）。"""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                conn.execute(
                    "DELETE FROM session_meta WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
                logger.info(f"[ChatDB] 已清空 session={session_id[:8]}…")
            finally:
                conn.close()

    def get_session_ids(self) -> list[str]:
        """返回数据库中所有会话 ID。"""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT session_id FROM sessions"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def session_message_count(self, session_id: str) -> int:
        """返回指定会话的消息总数。"""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def total_sessions(self) -> int:
        """返回数据库中的会话总数。"""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    # ==================== 恢复 ====================

    def load_session_into_store(self, session_id: str, store):
        """从 SQLite 加载指定会话的历史到内存 session_store。

        仅在 session_store 中无此会话记录时才加载（避免重复）。
        用于服务重启后恢复历史上下文。

        Args:
            session_id: 会话唯一标识。
            store:      SessionStore 实例。
        """
        if store.history_length(session_id) > 0:
            return  # 已有内存数据，跳过

        messages = self.get_history(session_id)
        for msg in messages:
            store.append(session_id, msg)

        if messages:
            logger.info(
                f"[ChatDB→SessionStore] 恢复 session={session_id[:8]}… "
                f"共 {len(messages)} 条消息"
            )


    # ==================== 用户画像（L0 长期记忆） ====================

    def get_user_profile(self, user_id: str) -> dict | None:
        """获取用户画像。

        Returns:
            用户画像 dict，不存在则返回 None。
        """
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT user_id, device_model, preferences, issues_log, extra, "
                "created_at, updated_at FROM user_profile WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "user_id": row[0],
                "device_model": row[1],
                "preferences": row[2],
                "issues_log": row[3],
                "extra": row[4],
                "created_at": row[5],
                "updated_at": row[6],
            }
        finally:
            conn.close()

    def upsert_user_profile(
        self,
        user_id: str,
        device_model: str | None = None,
        preferences: str | None = None,
        issues_log: str | None = None,
        extra: str | None = None,
    ):
        """创建或更新用户画像（按字段合并，不覆盖未传入的字段）。

        使用 INSERT OR REPLACE + COALESCE 实现增量更新。
        """
        existing = self.get_user_profile(user_id)
        if existing:
            new_device = device_model or existing["device_model"]
            new_prefs = preferences or existing["preferences"]
            new_issues = issues_log or existing["issues_log"]
            new_extra = extra or existing["extra"]
        else:
            new_device = device_model or ""
            new_prefs = preferences or "{}"
            new_issues = issues_log or "[]"
            new_extra = extra or "{}"

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO user_profile
                       (user_id, device_model, preferences, issues_log, extra, updated_at)
                       VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (user_id, new_device, new_prefs, new_issues, new_extra),
                )
                conn.commit()
                logger.info(
                    f"[ChatDB] 用户画像已更新: user={user_id}, "
                    f"device={new_device[:30] if new_device else 'N/A'}"
                )
            finally:
                conn.close()

    # ==================== 会话元数据（L1 会话标题） ====================

    def get_session_meta(self, session_id: str) -> dict | None:
        """兼容旧调用方，返回新 Session 记录。"""
        return self.get_session(session_id)

    def get_session(self, session_id: str) -> dict | None:
        """获取不可变会话绑定和可变展示状态。"""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                """SELECT s.session_id, s.title, s.user_id, s.persona_id,
                          p.name, p.display_name, s.mode, s.summary, s.workspace,
                          s.message_count, s.created_at, s.updated_at
                   FROM sessions s
                   JOIN personas p ON p.persona_id = s.persona_id
                   WHERE s.session_id = ?""",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "session_id": row[0],
                "title": row[1],
                "user_id": row[2],
                "persona_id": row[3],
                "persona_name": row[4],
                "persona_display_name": row[5],
                "mode": row[6],
                "summary": row[7],
                "workspace": row[8],
                "message_count": row[9],
                "created_at": row[10],
                "updated_at": row[11],
            }
        finally:
            conn.close()

    def require_session(self, session_id: str) -> SessionContext:
        row = self.get_session(session_id)
        if row is None:
            raise KeyError(f"会话不存在：{session_id}")
        return SessionContext(
            session_id=row["session_id"],
            user_id=row["user_id"],
            persona_id=row["persona_id"],
            persona_name=row["persona_name"],
            persona_display_name=row["persona_display_name"],
            mode=row["mode"],
            title=row["title"],
            summary=row["summary"],
            workspace=row["workspace"],
        )

    def create_session(
        self,
        session_id: str,
        *,
        user_id: str,
        persona_id: str,
        mode: str,
        title: str = "",
    ) -> dict:
        """创建 Session；身份和模式绑定创建后不提供更新接口。"""
        if mode not in {"chat", "work"}:
            raise ValueError("mode 必须是 chat 或 work")
        persona = persona_catalog.require(persona_id)
        normalized_user = str(user_id or "local_user").strip() or "local_user"
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (normalized_user,))
                conn.execute(
                    """INSERT INTO sessions
                       (session_id, user_id, persona_id, mode, title)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, normalized_user, persona.persona_id, mode, title or "新会话"),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_session(session_id) or {}

    def clear_messages(self, session_id: str) -> None:
        """清空会话内容，但保留不可变的 Session 绑定。"""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM memories WHERE scope = 'session' AND session_id = ?", (session_id,))
                conn.execute(
                    """UPDATE sessions SET summary='', message_count=0,
                       updated_at=CURRENT_TIMESTAMP WHERE session_id=?""",
                    (session_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def upsert_session_meta(
        self,
        session_id: str,
        title: str | None = None,
        user_id: str | None = None,
        message_count: int | None = None,
    ):
        """创建或更新会话元数据。"""
        existing = self.get_session(session_id)
        if existing is None:
            self.create_session(
                session_id,
                user_id=user_id or "local_user",
                persona_id="cyrene",
                mode="chat",
                title=title or "新会话",
            )
            existing = self.get_session(session_id)
        new_title = title or (existing["title"] if existing else "")
        new_count = (
            message_count if message_count is not None
            else (existing["message_count"] if existing else 0)
        )

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """UPDATE sessions
                       SET title = ?, message_count = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE session_id = ?""",
                    (new_title, new_count, session_id),
                )
                conn.commit()
            finally:
                conn.close()

    def list_sessions_with_meta(self, limit: int = 20) -> list[dict]:
        """返回最近的会话列表（含标题）。"""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT s.session_id, COALESCE(NULLIF(s.title, ''), '新会话'),
                          s.user_id, s.persona_id, p.name, p.display_name, s.mode,
                          s.message_count, s.updated_at
                   FROM sessions s
                   JOIN personas p ON p.persona_id = s.persona_id
                   ORDER BY s.updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                {
                    "session_id": r[0],
                    "title": r[1],
                    "user_id": r[2],
                    "persona_id": r[3],
                    "persona_name": r[4],
                    "persona_display_name": r[5],
                    "mode": r[6],
                    "message_count": r[7],
                    "updated_at": r[8],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def update_session_summary(self, session_id: str, summary: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """UPDATE sessions SET summary = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE session_id = ?""",
                    (str(summary or "")[:4000], session_id),
                )
                conn.commit()
            finally:
                conn.close()

    def update_user_display_name(self, user_id: str, display_name: str) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """UPDATE users SET display_name=?, updated_at=CURRENT_TIMESTAMP
                       WHERE user_id=?""",
                    (display_name.strip()[:80], user_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_user_persona_profile(self, user_id: str, persona_id: str) -> dict | None:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """SELECT * FROM user_persona_profiles
                   WHERE user_id = ? AND persona_id = ?""",
                (user_id, persona_id),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def upsert_user_persona_profile(
        self,
        user_id: str,
        persona_id: str,
        *,
        preferred_address: str | None = None,
        relationship_stage: str | None = None,
        shared_experiences: list[str] | None = None,
    ) -> None:
        existing = self.get_user_persona_profile(user_id, persona_id) or {}
        try:
            existing_experiences = json.loads(existing.get("shared_experiences", "[]"))
        except (TypeError, json.JSONDecodeError):
            existing_experiences = []
        experiences = list(existing_experiences)
        for item in shared_experiences or []:
            if item not in experiences:
                experiences.append(item)
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """INSERT INTO user_persona_profiles
                       (user_id, persona_id, preferred_address,
                        relationship_stage, shared_experiences, updated_at)
                       VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(user_id, persona_id) DO UPDATE SET
                         preferred_address=excluded.preferred_address,
                         relationship_stage=excluded.relationship_stage,
                         shared_experiences=excluded.shared_experiences,
                         updated_at=CURRENT_TIMESTAMP""",
                    (
                        user_id,
                        persona_id,
                        preferred_address if preferred_address is not None else existing.get("preferred_address", ""),
                        relationship_stage if relationship_stage is not None else existing.get("relationship_stage", ""),
                        json.dumps(experiences, ensure_ascii=False),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def add_memory(
        self,
        *,
        scope: str,
        user_id: str,
        content: str,
        persona_id: str | None = None,
        session_id: str | None = None,
        source_quote: str = "",
        confidence: float = 0.7,
        importance: float = 0.5,
    ) -> int:
        if scope not in {"user_global", "user_persona", "session"}:
            raise ValueError(f"无效 memory scope：{scope}")
        if scope == "user_persona" and not persona_id:
            raise ValueError("user_persona memory 需要 persona_id")
        if scope == "session" and not session_id:
            raise ValueError("session memory 需要 session_id")
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute(
                    """INSERT INTO memories
                       (scope, user_id, persona_id, session_id, content,
                        source_quote, confidence, importance)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        scope, user_id, persona_id, session_id, content,
                        source_quote, confidence, importance,
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)
            finally:
                conn.close()

    def list_scoped_memories(
        self,
        session: SessionContext,
        *,
        limit_per_scope: int = 5,
    ) -> dict[str, list[str]]:
        conn = sqlite3.connect(self._db_path)
        try:
            def read(where: str, params: tuple) -> list[str]:
                rows = conn.execute(
                    f"""SELECT content FROM memories WHERE {where} AND status='active'
                        ORDER BY importance DESC, updated_at DESC LIMIT ?""",
                    (*params, limit_per_scope),
                ).fetchall()
                return [str(row[0]) for row in rows]

            return {
                "user_global": read("scope='user_global' AND user_id=?", (session.user_id,)),
                "user_persona": read(
                    "scope='user_persona' AND user_id=? AND persona_id=?",
                    (session.user_id, session.persona_id),
                ),
                "session": read("scope='session' AND session_id=?", (session.session_id,)),
            }
        finally:
            conn.close()


# ==================== 模块级单例 ====================

chat_db = ChatDB()
