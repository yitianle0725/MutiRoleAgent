"""
会话隔离存储层
==============
为每个 ``session_id`` 维护独立的消息历史列表，实现多会话完全隔离。

设计要点
--------
- **内存存储**：当前使用线程安全的进程内字典，服务重启后清空。
  后续可替换为 SQLite / Redis 实现持久化，接口不变。
- **隔离保证**：每个 ``session_id`` 拥有独立的消息列表，
  不同 session 之间互不可见、互不干扰。
- **消息格式**：存储原始 ``BaseMessage`` 列表，与 LangGraph State
  的 messages 字段格式一致，零转换成本。

使用方式::

    from utils.session_store import session_store

    history = session_store.get_history("session_abc")
    session_store.append("session_abc", msg)
    session_store.clear("session_abc")
"""

import threading
from typing import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from utils.logger_handler import logger


class SessionStore:
    """线程安全的会话历史存储。

    每个 session_id 对应一个 ``list[BaseMessage]``，
    按对话顺序追加，不做任何截断（截断由 context_trimmer 负责）。
    """

    def __init__(self):
        self._store: dict[str, list[BaseMessage]] = {}
        self._lock = threading.Lock()

    # ---- 读取 ----

    def get_history(self, session_id: str) -> list[BaseMessage]:
        """获取指定会话的完整消息历史（按时间顺序）。

        Args:
            session_id: 会话唯一标识。

        Returns:
            消息列表的浅拷贝，空会话返回空列表。
        """
        with self._lock:
            messages = self._store.get(session_id, [])
            return list(messages)  # 浅拷贝，防止外部意外修改

    def history_length(self, session_id: str) -> int:
        """返回指定会话的消息数量。"""
        with self._lock:
            return len(self._store.get(session_id, []))

    # ---- 写入 ----

    def append(self, session_id: str, message: BaseMessage):
        """向指定会话追加一条消息。

        Args:
            session_id: 会话唯一标识。
            message:    待追加的消息（HumanMessage / AIMessage / ToolMessage 等）。
        """
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = []
            self._store[session_id].append(message)
            logger.debug(
                f"[SessionStore] session={session_id} "
                f"+1 msg ({type(message).__name__}), "
                f"total={len(self._store[session_id])}"
            )

    def append_pair(self, session_id: str, user_msg: str, assistant_msg: str):
        """同时追加一对用户消息和助手回复。

        便捷方法，内部创建 HumanMessage 和 AIMessage。
        """
        self.append(session_id, HumanMessage(content=user_msg))
        self.append(session_id, AIMessage(content=assistant_msg))

    # ---- 管理 ----

    def clear(self, session_id: str):
        """清空指定会话的全部历史。"""
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                logger.info(f"[SessionStore] 已清空 session={session_id}")

    def list_sessions(self) -> list[str]:
        """返回所有活跃会话的 ID 列表。"""
        with self._lock:
            return list(self._store.keys())

    def total_sessions(self) -> int:
        """返回当前活跃会话总数。"""
        with self._lock:
            return len(self._store)

    def total_messages(self) -> int:
        """返回所有会话的消息总数。"""
        with self._lock:
            return sum(len(msgs) for msgs in self._store.values())


# ==================== 模块级单例 ====================

session_store = SessionStore()
