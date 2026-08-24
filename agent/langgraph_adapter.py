"""LangGraph P0 适配器。

集中管理 compiled agent 的配置，避免各入口自行拼接 config。LangGraph
未安装 checkpoint 扩展或未启用时，默认返回空配置，兼容现有行为。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


def build_graph_config(
    *,
    session_id: str,
    thread_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """构造 LangGraph RunnableConfig。

    `thread_id` 是图状态线程，`run_id` 仅作为业务追踪字段，二者有意分开。
    """

    resolved_thread_id = thread_id or session_id
    configurable: dict[str, Any] = {
        "thread_id": resolved_thread_id,
        "session_id": session_id,
    }
    if run_id:
        configurable["run_id"] = run_id
    return {
        "configurable": configurable,
        "metadata": {
            "session_id": session_id,
            "thread_id": resolved_thread_id,
            **({"run_id": run_id} if run_id else {}),
        },
    }


def checkpointer_enabled() -> bool:
    """P0 默认关闭持久化，设置环境变量后启用适配器。"""

    return os.getenv("LANGGRAPH_CHECKPOINT_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def build_memory_checkpointer() -> Any | None:
    """创建开发用 MemorySaver；失败时安全降级。"""

    if not checkpointer_enabled():
        return None
    try:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    except (ImportError, AttributeError):
        return None


_CHECKPOINTER_LOCK = threading.Lock()
_CHECKPOINTER: Any | None = None


def build_checkpointer() -> Any | None:
    """按配置创建进程级共享 checkpointer。

    SQLite saver 是可选依赖；未安装时明确降级为 MemorySaver，避免应用无法启动。
    """

    global _CHECKPOINTER
    if not checkpointer_enabled():
        return None
    with _CHECKPOINTER_LOCK:
        if _CHECKPOINTER is not None:
            return _CHECKPOINTER
        mode = os.getenv("LANGGRAPH_CHECKPOINT_MODE", "memory").lower()
        if mode == "sqlite":
            try:
                from langgraph.checkpoint.sqlite import SqliteSaver

                path = Path(os.getenv("LANGGRAPH_CHECKPOINT_PATH", "data/langgraph_checkpoints.db"))
                path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(str(path), check_same_thread=False)
                _CHECKPOINTER = SqliteSaver(connection)
                setup = getattr(_CHECKPOINTER, "setup", None)
                if callable(setup):
                    setup()
                return _CHECKPOINTER
            except (ImportError, AttributeError, OSError):
                # 可选扩展未安装时使用内存实现，保持本地开发可启动。
                pass
        _CHECKPOINTER = build_memory_checkpointer()
        return _CHECKPOINTER
