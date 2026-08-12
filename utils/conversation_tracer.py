"""
对话诊断追踪器
==============
完整追踪多轮对话的每一步，帮助定位 "第二轮卡住" 这类问题。

追踪点覆盖整个链路::

    execute_stream_async 入口
    ├── 1. 加载历史 (session_store)
    ├── 2. 裁剪上下文 (trim_history)
    ├── 3. 决策路由 (DecisionEngine)
    ├── 4a. Chat 路径 (chat_model.astream)
    ├── 4b. Agent 路径 (LangGraph ReAct)
    │       ├── 模型调用前 (middleware)
    │       ├── 工具调用
    │       └── 模型调用后
    ├── 5. 持久化 (session_store + chat_db)
    └── 出口 (总耗时)

用法::

    from utils.conversation_tracer import ConversationTracer

    tracer = ConversationTracer(session_id="abc", trace_id="1a2b3c4d")
    tracer.enter(query="你好")
    ...
    tracer.exit()

所有日志通过 ``utils.logger_handler.logger`` 输出，级别为 INFO，
带 ``[ConvTrace]`` 前缀，方便 grep。
"""

from __future__ import annotations

import asyncio
import time
from typing import Sequence

from langchain_core.messages import BaseMessage

from utils.logger_handler import logger

# ==================== 辅助 ====================


def _event_loop_id() -> str:
    """当前事件循环的短标识（用于检测事件循环切换问题）。"""
    try:
        loop = asyncio.get_running_loop()
        return f"loop={id(loop) % 10000:04d}"
    except RuntimeError:
        return "loop=NONE"


def _msg_summary(messages: Sequence[BaseMessage]) -> str:
    """消息列表摘要：条数 + 类型分布 + token 估算。"""
    if not messages:
        return "0条"

    from utils.context_trimmer import estimate_message_tokens

    types: dict[str, int] = {}
    for m in messages:
        t = type(m).__name__
        types[t] = types.get(t, 0) + 1

    total_tokens = sum(estimate_message_tokens(m) for m in messages)
    type_str = " ".join(f"{k}={v}" for k, v in sorted(types.items()))
    return f"{len(messages)}条 [{type_str}] ~{total_tokens}tok"


# ==================== 追踪器 ====================


class ConversationTracer:
    """多轮对话诊断追踪器。

    在 ``react_agent.py`` 的 ``execute_stream_async`` 中嵌入，
    每一步记录时间戳、状态摘要和关键决策。
    """

    def __init__(self, session_id: str, trace_id: str):
        self.session_id = session_id
        self.trace_id = trace_id
        self._t0 = time.time()
        self._step_times: dict[str, float] = {}
        self._step_idx = 0

    # ---- 内部 ----

    @property
    def _prefix(self) -> str:
        return f"[ConvTrace|{self.trace_id}|{self.session_id[:8]}]"

    def _log(self, step: str, detail: str = "", level: str = "info"):
        elapsed = (time.time() - self._t0) * 1000
        self._step_idx += 1
        msg = f"{self._prefix} #{self._step_idx} [{step}] ({elapsed:.0f}ms) {detail}"
        if level == "warn":
            logger.warning(msg)
        elif level == "error":
            logger.error(msg)
        else:
            logger.info(msg)

    def _mark(self, name: str):
        self._step_times[name] = time.time()

    # ---- 追踪点 ----

    def enter(self, query: str):
        """入口：记录用户 query 和初始状态。"""
        self._log(
            "ENTER",
            f'query="{query[:60]}" {_event_loop_id()}',
        )

    def load_history(self, messages: Sequence[BaseMessage]):
        """加载历史后：记录消息数和类型分布。"""
        self._mark("load")
        rounds = self._count_rounds(messages)
        self._log(
            "LOAD_HISTORY",
            f"{_msg_summary(messages)} {rounds}轮 {_event_loop_id()}",
        )

    def after_trim(
        self,
        before: Sequence[BaseMessage],
        after: Sequence[BaseMessage],
    ):
        """裁剪后：记录裁剪前后对比。"""
        self._mark("trim")
        before_rounds = self._count_rounds(before)
        after_rounds = self._count_rounds(after)
        dropped = len(before) - len(after)

        if dropped > 0:
            self._log(
                "TRIM",
                f"裁剪: {len(before)}条→{len(after)}条 "
                f"({before_rounds}轮→{after_rounds}轮, -{dropped}条)",
                level="warn",
            )
        else:
            self._log(
                "TRIM",
                f"无需裁剪: {len(after)}条 {after_rounds}轮",
            )

    def decision(
        self,
        route: str,
        confidence: float,
        reason: str,
        cache_streak: int = 0,
    ):
        """决策路由后：记录路由目标和置信度。"""
        self._mark("decision")
        cache_note = f" streak={cache_streak}" if cache_streak else ""
        self._log(
            "DECISION",
            f"→ {route.upper()} conf={confidence:.2f} "
            f'"{reason}"{cache_note} {_event_loop_id()}',
        )

    def chat_path_start(self, history_count: int):
        """Chat 路径开始。"""
        self._mark("chat_start")
        self._log(
            "CHAT_START",
            f"直接 LLM 调用, 历史={history_count}条 {_event_loop_id()}",
        )

    def chat_path_done(self, response_len: int):
        """Chat 路径完成。"""
        elapsed = self._elapsed_since("chat_start")
        self._log(
            "CHAT_DONE",
            f"响应={response_len}字 耗时={elapsed:.1f}s",
        )

    def agent_path_start(self, state_msg_count: int):
        """Agent 路径开始。"""
        self._mark("agent_start")
        self._log(
            "AGENT_START",
            f"ReAct 循环, state消息={state_msg_count}条 {_event_loop_id()}",
        )

    def agent_model_before(self, msg_count: int):
        """Agent 路径：模型调用前。"""
        self._log(
            "AGENT_MODEL_BEFORE",
            f"发送 {msg_count} 条消息给 LLM",
        )

    def agent_tool_call(self, tool_name: str):
        """Agent 路径：工具调用。"""
        self._log(
            "AGENT_TOOL",
            f"调用工具: {tool_name}",
        )

    def agent_tool_done(self, tool_name: str, result_len: int):
        """Agent 路径：工具完成。"""
        self._log(
            "AGENT_TOOL_DONE",
            f"工具完成: {tool_name} 结果={result_len}字",
        )

    def agent_path_done(self, response_len: int, tokens: dict):
        """Agent 路径完成。"""
        elapsed = self._elapsed_since("agent_start")
        self._log(
            "AGENT_DONE",
            f"响应={response_len}字 tokens={tokens} 耗时={elapsed:.1f}s",
        )

    def persist(self, store_count: int, db_count: int):
        """持久化后：记录存储状态。"""
        self._mark("persist")
        self._log(
            "PERSIST",
            f"session_store={store_count}条 chat_db={db_count}条",
        )

    def exit(self, error: str = ""):
        """出口：记录总耗时或异常。"""
        total = (time.time() - self._t0) * 1000
        if error:
            self._log(
                "EXIT_ERROR",
                f"总耗时={total:.0f}ms 错误={error}",
                level="error",
            )
        else:
            self._log(
                "EXIT_OK",
                f"总耗时={total:.0f}ms",
            )

    # ---- 辅助 ----

    @staticmethod
    def _count_rounds(messages: Sequence[BaseMessage]) -> int:
        """数对话轮数（每个 HumanMessage 算一轮）。"""
        from langchain_core.messages import HumanMessage
        return sum(1 for m in messages if isinstance(m, HumanMessage))

    def _elapsed_since(self, step_name: str) -> float:
        """从某个步骤到现在的耗时（秒）。"""
        t0 = self._step_times.get(step_name, self._t0)
        return time.time() - t0
