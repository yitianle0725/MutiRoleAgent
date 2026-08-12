"""
Streamlit Channel
=================
将现有 Streamlit Web UI 封装为 channel，使其与 FastAPI Channel 共享同一套 Agent 缓存。

由于 Streamlit 的 ``streamlit run app.py`` 是独立进程（自带 Tornado 服务器），
此 channel 不管理 Streamlit 的服务器生命周期，仅作为轻量适配器：

1. 标记 Streamlit 为一个 channel
2. 提供 ``from channels.platforms.streamlit import channel`` 入口
3. 通过 ``channels.manager.agent_cache`` 与其它 channel 共享 Agent 缓存

实际 UI 逻辑仍在 ``app.py`` 中，通过 ``agent_cache`` 单例获取 Agent 实例。
"""

from channels.base import Channel


class StreamlitChannel(Channel):
    """Streamlit Web UI channel。

    Streamlit 通过 ``streamlit run app.py`` 启动，有其自己的服务器生命周期，
    因此 ``start()`` / ``stop()`` 仅管理运行状态标记，不负责服务器启停。
    """

    name = "streamlit"

    async def start(self) -> None:
        """标记 channel 为运行中（Streamlit 由独立进程管理）。"""
        self._running = True

    async def stop(self) -> None:
        """标记 channel 为已停止。"""
        self._running = False


# ==================== 模块级单例 ====================

channel = StreamlitChannel()
