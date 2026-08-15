"""
Agent 中间件
===========
LangGraph 中间件系统，通过三个钩子实现横切关注点：

1. ``@wrap_tool_call`` — 工具调用拦截（日志 + 上下文标记）
2. ``@before_model``  — 模型调用前日志
3. ``@dynamic_prompt`` — 动态提示词组合（persona + work_mode）

动态提示词组合规则
------------------
最终 system prompt = **[角色人设 overlay]** + **[工作模式 base prompt]**

- **角色人设 (persona)**：从 ``runtime.context["persona"]`` 读取角色名，
  调用 ``persona_loader`` 生成语气/人设/对话风格的约束文本。
  ``None`` / ``"none"`` 表示无角色（默认专业客服模式）。
- **工作模式 (work_mode)**：从 ``runtime.context["report"]`` 读取布尔值。
  ``True`` → 报告写手模式（``report_prompt.txt``）；
  ``False`` → 默认客服模式（``main_prompt.txt``）。
"""

from typing import Callable

from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest
from langchain_core.messages import ToolMessage, HumanMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from utils.logger_handler import logger
from utils.prompt_loader import load_report_prompts, load_system_prompts
from utils.persona_loader import load_persona_overlay
from agent.action_gate import action_gate
from agent.execution_policy import validate_tool_args
from agent.cita_classifier import classify_intent, build_cita_overlay
from agent.tool_wrapper import execute_with_safety
from agent.user_profile_extractor import build_profile_context


# ==================== 工具调用中间件 ====================

@wrap_tool_call
def monitor_tool(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """拦截所有工具调用，记录日志；特别处理上下文标记工具。

    支持的上下文标记工具：
    - ``switch_persona``  → 设置 runtime.context["persona"] = 角色名
    - ``reset_persona``   → 清除 runtime.context["persona"]
    """
    tool_name = request.tool_call["name"]
    tool_args = request.tool_call.get("args", {})
    tool_call_id = request.tool_call.get("id", "")

    logger.info(f"[tool monitor] 执行工具：{tool_name}")
    logger.info(f"[tool monitor] 传入参数：{tool_args}")

    # ============ Action Gate 运行时拦截 ============
    gate_result = action_gate.check_tool_call(tool_name, tool_args)
    if not gate_result.allow:
        logger.warning(f"[Action Gate] 运行时拦截: {tool_name} — {gate_result.reason}")
        return ToolMessage(
            content=f"[工具调用被拒绝] {gate_result.reason}",
            tool_call_id=tool_call_id,
        )

    # ============ Execution Policy 参数校验 ============
    policy_result = validate_tool_args(tool_name, tool_args)
    if not policy_result.valid:
        logger.warning(
            f"[Exec Policy] 参数校验失败: {tool_name} — {policy_result.error_message}"
        )
        return ToolMessage(
            content=f"[参数错误] {policy_result.error_message}。"
                    f"请修正参数后重新调用工具。",
            tool_call_id=tool_call_id,
        )

    # ============ 实际执行（统一超时/容错/日志包装） ============
    result = execute_with_safety(handler, request, tool_name, tool_call_id)

    # 如果包装器返回了错误 ToolMessage（以 "[工具" 开头），跳过上下文标记
    is_error = (
        isinstance(result, ToolMessage)
        and result.content
        and str(result.content).startswith("[工具")
    )

    if not is_error and request.runtime.context is not None:
        # ---- 上下文标记处理 ----
        if tool_name == "switch_persona":
            persona_name = tool_args.get("persona_name", "")
            request.runtime.context["persona"] = persona_name
            logger.info(f"[middleware] 已切换角色人设 → {persona_name}")

        elif tool_name == "reset_persona":
            request.runtime.context.pop("persona", None)
            logger.info("[middleware] 已重置为默认角色（无 persona）")

    return result


# ==================== 模型调用前中间件 ====================

@before_model
def log_before_model(
        state: AgentState,
        runtime: Runtime,
):
    """每次模型调用前：记录日志 + CITA 意图分类。

    从消息历史中找到最后一条用户消息，运行轻量规则分类器，
    分类结果存入 ``runtime.context["cita_intent"]``，
    供 ``compose_prompt`` 动态注入。
    """
    messages = state.get("messages", [])
    logger.info(f"[log_before_model] 即将调用模型，带有 {len(messages)} 条消息")

    if messages:
        last_msg = messages[-1]
        logger.debug(
            f"[log_before_model] {type(last_msg).__name__} | "
            f"{str(last_msg.content)[:80]}"
        )

        # ---- CITA 意图分类 ----
        # 找到最后一条用户消息（倒序遍历，跳过 ToolMessage / AIMessage）
        last_user_text = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    last_user_text = content
                elif isinstance(content, list):
                    # content 可能是 [{"type": "text", "text": "..."}]
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            parts.append(block["text"])
                    last_user_text = "".join(parts)
                break

        if last_user_text and runtime.context is not None:
            intent = classify_intent(last_user_text)
            runtime.context["cita_intent"] = intent
            logger.info(
                f"[CITA] 意图分类: type={intent.intent_type} | "
                f"emotions={intent.emotions} | "
                f"needs_rag={intent.needs_rag} | "
                f"needs_web={intent.needs_web_search} | "
                f"confidence={intent.confidence:.2f}"
            )

    return None


# ==================== 动态提示词中间件 ====================

@dynamic_prompt
def compose_prompt(request: ModelRequest) -> str:
    """组合最终 system prompt：persona overlay + base prompt。

    读取优先级：
    1. ``runtime.context["persona"]`` — 运行时切换（最高优先级）
    2. ``state["persona"]``           — 初始传入值（回退）
    3. ``runtime.context["report"]``  — 是否报告模式

    最终结构::

        [角色人设 overlay (若有)]
        ---
        [工作指令 (main 或 report)]
    """
    # persona: runtime.context 优先（工具切换），state 回退（初始值）
    ctx = request.runtime.context or {}
    persona_name: str | None = (
        ctx.get("persona")
        or request.state.get("persona")
    )
    # DEBUG: 打印 state 中的 persona 字段
    logger.info(
        f"[compose_prompt DEBUG] ctx.persona={ctx.get('persona')}, "
        f"state.persona={request.state.get('persona')}, "
        f"state keys={list(request.state.keys())[:10]}"
    )
    # 显式传入 "none" 则清除角色
    if persona_name and persona_name.lower() == "none":
        persona_name = None

    is_report: bool = ctx.get("report", False)

    # 1) 角色人设层
    persona_overlay = load_persona_overlay(persona_name) if persona_name else ""

    # 2) 工作模式层
    base_prompt = load_report_prompts() if is_report else load_system_prompts()

    # 3) 拼接
    if persona_overlay:
        final_prompt = (
            f"你现在正在扮演角色「{persona_name}」，你必须严格遵循以下人设进行对话：\n\n"
            f"{persona_overlay}\n\n"
            f"---\n\n"
            f"## 工作指令\n\n"
            f"{base_prompt}"
        )
    else:
        final_prompt = base_prompt

    # 4) 用户画像注入（L0 长期记忆，CITA 之后、persona 之前）
    user_id = request.state.get("user_id")
    profile_context = build_profile_context(user_id)
    if profile_context:
        final_prompt = (
            f"{profile_context}\n\n"
            f"---\n\n"
            f"{final_prompt}"
        )
        logger.info(f"[compose_prompt] 用户画像注入: user={user_id}")

    # 5) CITA 意图提示（最前面，优先级最高）
    cita_intent = ctx.get("cita_intent")
    if cita_intent is not None:
        cita_overlay = build_cita_overlay(cita_intent)
        if cita_overlay:
            final_prompt = (
                f"## 当前对话上下文（系统自动分析，仅供参考）\n"
                f"{cita_overlay}\n\n"
                f"---\n\n"
                f"{final_prompt}"
            )
            logger.info(
                f"[compose_prompt] CITA 叠加: type={cita_intent.intent_type} | "
                f"emotions={cita_intent.emotions}"
            )

    # 5) 最终日志
    logger.info(
        f"[compose_prompt] {'角色模式: ' + persona_name if persona_name else '无角色'} | "
        f"工作模式: {'报告' if is_report else '客服'} | "
        f"总长度: {len(final_prompt)} 字符"
    )

    return final_prompt
