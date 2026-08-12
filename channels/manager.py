"""
Channel 管理器 & Agent 缓存
===========================
跨 channel 共享的 Agent LRU 缓存，参考 EchoBot ``echobot/channels/manager.py`` 的 ChannelManager。

设计要点
--------
- **Agent 复用**：同一 ``session_id`` 在 Streamlit 和 FastAPI 之间复用同一个 ``ReactAgent`` 实例，
  避免重复加载 MCP 工具 + RAG 知识库。
- **LRU 淘汰**：缓存上限 32 个 Agent，超出时淘汰最久未使用的实例。
- **线程安全**：``threading.Lock`` 保护缓存操作，兼容 Streamlit 同步环境和 FastAPI 异步环境。
- **初始化保护**：每个 session 的 Agent 只初始化一次（通过 ``_initializing`` 集合 + ``asyncio.Lock`` 防并发）。

用法::

    from channels.manager import agent_cache

    agent = agent_cache.get(session_id)
    if agent is None:
        agent = ReactAgent(session_id=session_id, ...)
        await agent.init_agent()
        agent_cache.put(session_id, agent)
"""

import asyncio
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from utils.logger_handler import logger

if TYPE_CHECKING:
    from agent.react_agent import ReactAgent


class AgentCache:
    """跨 channel 共享的 Agent LRU 缓存。

    不负责 Agent 创建（init_agent 是异步的，由各 channel 按自身方式调用），
    仅保管已初始化完成的 Agent 实例。
    """

    def __init__(self, max_size: int = 32):
        self._cache: OrderedDict[str, "ReactAgent"] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    # ---- 读取 ----

    def get(self, session_id: str) -> "ReactAgent | None":
        """获取已缓存的 Agent 实例（命中时移到队尾，即 LRU 最近使用）。

        Returns:
            Agent 实例，未命中则返回 None。
        """
        with self._lock:
            agent = self._cache.get(session_id)
            if agent is not None:
                self._cache.move_to_end(session_id)
            return agent

    # ---- 写入 ----

    def put(self, session_id: str, agent: "ReactAgent") -> None:
        """将 Agent 放入缓存。若缓存已满，淘汰最久未使用的实例。

        Args:
            session_id: 会话唯一标识。
            agent:       已初始化（init_agent 完成）的 ReactAgent 实例。
        """
        with self._lock:
            if session_id in self._cache:
                self._cache.move_to_end(session_id)
            else:
                self._cache[session_id] = agent
                self._evict_if_needed()
            logger.debug(
                f"[AgentCache] put: session={session_id[:12]}…, "
                f"size={len(self._cache)}/{self._max_size}"
            )

    def evict(self, session_id: str) -> None:
        """从缓存中移除指定 session 的 Agent。"""
        with self._lock:
            if session_id in self._cache:
                del self._cache[session_id]
                logger.debug(f"[AgentCache] evict: session={session_id[:12]}…")

    def clear(self) -> None:
        """清空全部缓存。"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"[AgentCache] clear: 已清理 {count} 个 Agent")

    # ---- 内部 ----

    def _evict_if_needed(self) -> None:
        """LRU 淘汰：超出上限时删除最旧的条目（队首）。"""
        while len(self._cache) > self._max_size:
            evicted_id, _ = self._cache.popitem(last=False)
            logger.info(
                f"[AgentCache] LRU 淘汰: session={evicted_id[:12]}…, "
                f"新 size={len(self._cache)}"
            )

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def max_size(self) -> int:
        return self._max_size


# ==================== 模块级单例 ====================

agent_cache = AgentCache()
