"""
会话状态定义模块
================
定义 LangGraph 图运行标准格式的 AgentState，用于在整个 Agent 生命周期中
持久化消息历史和会话标识。

LangGraph 的 State 是 TypedDict + Annotated reducer 模式：
- messages 字段使用 operator.add 作为 reducer，每次图节点返回新消息时
  自动追加到历史中（而非覆盖），这是 LangGraph 消息累加的标准注解。
- session_id 为字符串类型，无 reducer 则默认覆盖上一次的值。
"""

from typing import TypedDict, Annotated, Sequence, Any
import operator
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """
    Agent 会话状态，适配 LangGraph 图运行标准格式。

    Attributes:
        messages:
            对话消息序列，使用 ``operator.add`` 作为 reducer——
            每次图节点输出新消息时自动追加到已有消息列表末尾，
            而非覆盖整个字段。这是 LangGraph 消息累加的标准范式。
        session_id:
            会话唯一标识，用于区分不同用户/会话。
            无 reducer，每次赋值直接覆盖。
        user_id:
            当前用户 ID（可选），由外部系统传入，报告生成时使用。
        report_context:
            报告模式标记（可选），由中间件运行时写入，
            控制动态提示词切换状态。
        persona:
            角色人设名称（可选），如 ``"Cyrene"``。
            ``None`` 表示默认专业客服模式。
            初始值由 ``ReactAgent(default_persona=...)`` 注入，
            运行时可通过 ``switch_persona`` / ``reset_persona`` 工具动态修改。
    """
    messages: Annotated[Sequence[BaseMessage], operator.add]
    session_id: str
    user_id: str | None
    report_context: bool
    persona: str | None
    thread_id: str
    agent_summary: str
    facts: list[dict[str, Any]]
    errors: list[str]


# ==================== 工厂函数 ====================

def create_agent_state(
    user_query: str,
    session_id: str = "default",
    user_id: str | None = None,
    report_context: bool = False,
    persona: str | None = None,
    history: Sequence[BaseMessage] | None = None,
    thread_id: str | None = None,
) -> AgentState:
    """构造符合 LangGraph 图运行标准格式的 AgentState。

    将构造逻辑封装在模块级别，保持 TypedDict 的纯粹性，
    同时提供语义明确的工厂入口。

    Args:
        user_query:    用户本轮输入文本。
        session_id:    会话唯一标识。
        user_id:       当前用户 ID（可选）。
        report_context: 是否处于报告生成模式。
        persona:       角色人设名称（可选），如 "Cyrene"，None 表示默认。
        history:       历史消息列表（可选），会拼接在当前 query 之前，
                       实现多轮对话的上下文连续性。

    Returns:
        可直接传入 ``agent.astream()`` 的 AgentState 字典。
    """
    messages: list = list(history) if history else []
    messages.append(("user", user_query))

    return AgentState(
        messages=messages,
        session_id=session_id,
        user_id=user_id,
        report_context=report_context,
        persona=persona,
        thread_id=thread_id or session_id,
        agent_summary="",
        facts=[],
        errors=[],
    )
