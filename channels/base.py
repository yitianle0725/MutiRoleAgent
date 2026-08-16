"""
Channel 抽象基类
================
参考 EchoBot ``echobot/channels/base.py`` 的 adapter 模式。

每个 Channel 代表一种用户与 Agent 交互的方式（Streamlit Web UI、FastAPI REST/SSE/WS 等）。
不同 channel 共享同一套 Agent 实例（通过 ``channels.manager.agent_cache``）、
数据库（``memory.chat_db.chat_db``）和会话存储（``memory.session_store.session_store``）。

用法::

    from channels.base import Channel

    class MyChannel(Channel):
        name = "my_channel"

        async def start(self) -> None: ...
        async def stop(self) -> None: ...
"""

from abc import ABC, abstractmethod


class Channel(ABC):
    """交互渠道抽象基类。

    每个子类通过 ``name`` 属性标识自身，通过 ``start()`` / ``stop()``
    管理生命周期。具体传输协议（HTTP、WebSocket、Streamlit 等）由子类实现。
    """

    name: str = "base"

    @abstractmethod
    async def start(self) -> None:
        """启动 channel（异步）。"""
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """优雅关闭 channel。"""
        raise NotImplementedError

    @property
    def is_running(self) -> bool:
        return getattr(self, "_running", False)
