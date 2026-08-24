"""LangGraph AgentCore 适配边界。

项目不重复实现模型-工具循环；具体循环仍由 LangGraph compiled graph 提供。
该类只统一 graph 的配置、流式调用和结果入口，避免 Web/CLI 直接操作图对象。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from .langgraph_adapter import build_graph_config


class LangGraphAgentCore:
    """对 LangGraph compiled graph 的最小异步适配器。"""

    def __init__(self, graph: Any, *, session_id: str, thread_id: str | None = None) -> None:
        self.graph = graph
        self.session_id = session_id
        self.thread_id = thread_id or session_id

    def config(self, *, run_id: str | None = None) -> dict[str, Any]:
        return build_graph_config(session_id=self.session_id, thread_id=self.thread_id, run_id=run_id)

    async def astream(
        self,
        state: Any,
        *,
        run_id: str | None = None,
        stream_mode: str = "values",
    ) -> AsyncIterator[Any]:
        """统一调用 graph.astream；工具/模型循环由 LangGraph 负责。"""
        config = self.config(run_id=run_id)
        async for item in self.graph.astream(state, config=config, stream_mode=stream_mode):
            yield item

    async def ainvoke(self, state: Any, *, run_id: str | None = None) -> Any:
        return await self.graph.ainvoke(state, config=self.config(run_id=run_id))

    async def resume(self, value: Any, *, run_id: str | None = None) -> Any:
        """使用 LangGraph Command(resume=...) 恢复 interrupt 节点。"""
        from langgraph.types import Command
        return await self.graph.ainvoke(Command(resume=value), config=self.config(run_id=run_id))
