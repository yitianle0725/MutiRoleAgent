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

    from db.chat_db import chat_db

    chat_db.init_db()                              # 启动时建表
    chat_db.save_message("abc", "user", "你好")     # 保存用户消息
    chat_db.save_message("abc", "assistant", "你好")# 保存 AI 回复
    history = chat_db.get_history("abc")           # 查询会话历史
    chat_db.clear_session("abc")                   # 清空会话
"""

import sqlite3
import threading
from datetime import datetime
from typing import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from utils.logger_handler import logger
from utils.path_tool import get_abs_path

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
                conn.commit()
                logger.info(f"[ChatDB] 表初始化完成: {self._db_path}")
            finally:
                conn.close()

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
                    "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, role, content),
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
                    "INSERT INTO chat_history (session_id, role, content) VALUES (?, 'user', ?)",
                    (session_id, user_msg),
                )
                conn.execute(
                    "INSERT INTO chat_history (session_id, role, content) VALUES (?, 'assistant', ?)",
                    (session_id, assistant_msg),
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
                """SELECT role, content FROM chat_history
                   WHERE session_id = ?
                   ORDER BY created_at ASC, id ASC
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
                """SELECT role, content, created_at FROM chat_history
                   WHERE session_id = ?
                   ORDER BY created_at ASC, id ASC
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
                conn.execute(
                    "DELETE FROM chat_history WHERE session_id = ?",
                    (session_id,),
                )
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
                "SELECT DISTINCT session_id FROM chat_history"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def session_message_count(self, session_id: str) -> int:
        """返回指定会话的消息总数。"""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_history WHERE session_id = ?",
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
                "SELECT COUNT(DISTINCT session_id) FROM chat_history"
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
        """获取会话元数据。"""
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT session_id, title, user_id, message_count, "
                "created_at, updated_at FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "session_id": row[0],
                "title": row[1],
                "user_id": row[2],
                "message_count": row[3],
                "created_at": row[4],
                "updated_at": row[5],
            }
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
        existing = self.get_session_meta(session_id)
        new_title = title or (existing["title"] if existing else "")
        new_user_id = user_id or (existing["user_id"] if existing else "")
        new_count = (
            message_count if message_count is not None
            else (existing["message_count"] if existing else 0)
        )

        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO session_meta
                       (session_id, title, user_id, message_count, updated_at)
                       VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (session_id, new_title, new_user_id, new_count),
                )
                conn.commit()
            finally:
                conn.close()

    def list_sessions_with_meta(self, limit: int = 20) -> list[dict]:
        """返回最近的会话列表（含标题）。"""
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                """SELECT s.session_id, s.title, s.user_id, s.message_count, s.updated_at
                   FROM session_meta s
                   ORDER BY s.updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                {
                    "session_id": r[0],
                    "title": r[1],
                    "user_id": r[2],
                    "message_count": r[3],
                    "updated_at": r[4],
                }
                for r in rows
            ]
        finally:
            conn.close()


# ==================== 模块级单例 ====================

chat_db = ChatDB()
