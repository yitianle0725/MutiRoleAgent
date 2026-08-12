"""
统一中间件
==========
将 Action Gate + Execution Policy + Tool Wrapper + CITA + Persona
合并为一个 LangGraph AgentMiddleware 子类，避免多个中间件对象冲突。
"""

from typing import Callable

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from utils.logger_handler import logger
from utils.prompt_loader import load_report_prompts, load_system_prompts
from utils.persona_loader import load_persona_overlay
from agent.action_gate import action_gate
from agent.execution_policy import validate_tool_args
from agent.cita_classifier import classify_intent, build_cita_overlay
from agent.cita.semantic import SemanticEngine, SemanticAnalysis
from agent.cita.budget import TokenBudget, BudgetStatus, estimate_tokens
from agent.tool_wrapper import execute_with_safety
from agent.user_profile_extractor import build_profile_context


# ==================== 工具分组：按领域动态裁剪 ====================
# 减少每次 LLM 请求携带的工具 schema，降低延迟和 token 消耗。
# 工具名集合，用于 awrap_model_call 中按 CITA 分析结果动态过滤。

# 每个领域对应的工具名集合
_TOOL_DOMAIN_MAP: dict[str, set[str]] = {
    "weather":  {"maps_weather", "maps_ip_location", "get_public_ip"},
    "anime":    {"search_anime", "fetch_anime", "get_season_anime"},
    "knowledge": {"rag_summarize"},
}
# 始终携带的轻量工具（schema 小，不影响延迟）
_ALWAYS_TOOLS: set[str] = {
    "get_current_time",           # 日期时间，轻量且高频
    "switch_persona", "reset_persona",  # 角色切换
    "list_skills", "invoke_skill",      # Skill 系统入口
}


class UnifiedMiddleware(AgentMiddleware):
    """合并所有中间件功能到一个对象中。

    钩子执行顺序：
    1. before_model  → CITA 意图分类 + 用户画像 + 角色人设 + 动态 prompt
    2. wrap_tool_call → Action Gate → Execution Policy → execute_with_safety
    """

    def __init__(self):
        super().__init__()

    # ==================== 工具调用拦截（同步 + 异步） ====================

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """异步版：astream 时走此路径。Gate/Policy 检查后直接 await handler。"""
        tool_name = request.tool_call["name"]
        tool_args = request.tool_call.get("args", {})
        tool_call_id = request.tool_call.get("id", "")

        logger.info(f"[middleware] 执行工具: {tool_name}, args={tool_args}")

        # 1) Action Gate
        gate_result = action_gate.check_tool_call(tool_name, tool_args)
        if not gate_result.allow:
            logger.warning(f"[Action Gate] 拦截: {tool_name}")
            return ToolMessage(
                content=f"[工具调用被拒绝] {gate_result.reason}",
                tool_call_id=tool_call_id, name=tool_name,
            )

        # 2) Execution Policy
        policy_result = validate_tool_args(tool_name, tool_args)
        if not policy_result.valid:
            logger.warning(f"[Exec Policy] 校验失败: {tool_name}")
            return ToolMessage(
                content=f"[参数错误] {policy_result.error_message}",
                tool_call_id=tool_call_id, name=tool_name,
            )

        # 3) 直接 await handler（async 不需要 ThreadPoolExecutor）
        try:
            result = await handler(request)
            logger.info(f"[middleware] 工具完成: {tool_name}")
        except Exception as e:
            logger.error(f"[middleware] 工具执行异常: {tool_name}: {e}")
            return ToolMessage(
                content=f"[工具执行失败] {tool_name}: {type(e).__name__}: {str(e)[:150]}",
                tool_call_id=tool_call_id, name=tool_name,
            )

        # 4) 上下文标记
        if request.runtime.context is not None:
            if tool_name == "switch_persona":
                request.runtime.context["persona"] = tool_args.get("persona_name", "")
            elif tool_name == "reset_persona":
                request.runtime.context.pop("persona", None)
            # Phase 6: 跟踪活跃 Skill（用于结构化输出注入）
            elif tool_name == "invoke_skill":
                skill_name = tool_args.get("skill_name", "")
                if skill_name:
                    request.runtime.context["_active_skill"] = skill_name
                    logger.info(f"[middleware] 激活 Skill: {skill_name}")

        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        tool_name = request.tool_call["name"]
        tool_args = request.tool_call.get("args", {})
        tool_call_id = request.tool_call.get("id", "")

        logger.info(f"[middleware] 执行工具: {tool_name}, args={tool_args}")

        # 1) Action Gate 运行时拦截
        gate_result = action_gate.check_tool_call(tool_name, tool_args)
        if not gate_result.allow:
            logger.warning(f"[Action Gate] 拦截: {tool_name} — {gate_result.reason}")
            return ToolMessage(
                content=f"[工具调用被拒绝] {gate_result.reason}",
                tool_call_id=tool_call_id,
                name=tool_name,
            )

        # 2) Execution Policy 参数校验
        policy_result = validate_tool_args(tool_name, tool_args)
        if not policy_result.valid:
            logger.warning(f"[Exec Policy] 校验失败: {tool_name}")
            return ToolMessage(
                content=f"[参数错误] {policy_result.error_message}。请修正参数后重新调用。",
                tool_call_id=tool_call_id,
                name=tool_name,
            )

        # 3) 实际执行（统一超时/容错）
        result = execute_with_safety(handler, request, tool_name, tool_call_id)

        # 4) 上下文标记
        is_error = (
            isinstance(result, ToolMessage)
            and result.content
            and str(result.content).startswith("[工具")
        )
        if not is_error and request.runtime.context is not None:
            if tool_name == "switch_persona":
                request.runtime.context["persona"] = tool_args.get("persona_name", "")
                logger.info(f"[middleware] 角色 → {tool_args.get('persona_name', '')}")
            elif tool_name == "reset_persona":
                request.runtime.context.pop("persona", None)
                logger.info("[middleware] 角色已重置")
            # Phase 6: 跟踪活跃 Skill（用于结构化输出注入）
            elif tool_name == "invoke_skill":
                skill_name = tool_args.get("skill_name", "")
                if skill_name:
                    request.runtime.context["_active_skill"] = skill_name
                    logger.info(f"[middleware] 激活 Skill: {skill_name}")

        return result

    # ==================== 模型调用前（同步 + 异步） ====================

    async def abefore_model(self, state: AgentState, runtime: Runtime) -> None:
        """异步版：astream 时走此路径。"""
        self.before_model(state, runtime)

    def before_model(self, state: AgentState, runtime: Runtime) -> None:
        messages = state.get("messages", [])

        # ---- Phase 7: 日期时间注入（直接插入消息，确保模型看到） ----
        from datetime import datetime
        now = datetime.now()
        date_msg = (
            f"[系统上下文] 今天是 {now.strftime('%Y年%m月%d日')}，"
            f"星期{['一','二','三','四','五','六','日'][now.weekday()]}，"
            f"当前时间 {now.strftime('%H:%M')}。"
            f"你有能力回答日期时间问题——系统已提供当前日期，无需工具。"
        )
        # 移除旧日期消息（避免累积）
        def _is_date_msg(m) -> bool:
            if not isinstance(m, SystemMessage):
                return False
            content = m.content
            if isinstance(content, str):
                return content.startswith("[系统上下文]")
            return False

        filtered = [msg for msg in messages if not _is_date_msg(msg)]
        filtered.insert(0, SystemMessage(content=date_msg))
        state["messages"][:] = filtered

        logger.info(f"[middleware] 模型调用前: {len(messages)}→{len(filtered)} 条消息, 已注入日期: {now.strftime('%Y-%m-%d %H:%M')}")

        # CITA 2.0 语义分析
        last_user_text = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    last_user_text = content
                elif isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            parts.append(block["text"])
                    last_user_text = "".join(parts)
                break

        if last_user_text and runtime.context is not None:
            # CITA 2.0 语义引擎（实体提取 + 情绪检测 + 意图分类）
            try:
                engine = SemanticEngine()
                # 提取最近 3 条历史消息文本作为上下文
                recent_context = []
                for msg in messages[-6:-1]:  # 最后 5 条但不包括当前
                    content = msg.content if hasattr(msg, "content") else ""
                    if isinstance(content, str) and content.strip():
                        recent_context.append(content[:200])
                analysis = engine.analyze(last_user_text, context=recent_context)
                runtime.context["cita_analysis"] = analysis
                # V1 兼容：同时设置 cita_intent
                runtime.context["cita_intent"] = analysis
                logger.info(
                    f"[CITA 2.0] intent={analysis.primary_intent}, "
                    f"entities={[(e.type, e.value) for e in analysis.entities]}, "
                    f"emotions={[(s.emotion, f'{s.effective_intensity:.1f}') for s in analysis.emotions]}, "
                    f"rag={analysis.needs_rag}, web={analysis.needs_web_search}"
                )
            except Exception as e:
                logger.warning(f"[CITA 2.0] 语义分析降级为 V1: {e}")
                # 降级到 V1 分类器
                intent = classify_intent(last_user_text)
                runtime.context["cita_intent"] = intent
                logger.info(
                    f"[CITA V1] type={intent.intent_type}, "
                    f"emotions={intent.emotions}, "
                    f"rag={intent.needs_rag}"
                )

            # Token 预算追踪
            try:
                budget = TokenBudget()
                # 估算 system prompt（将在 dynamic_prompt 中更新）
                budget.track("system_prompt", estimate_tokens(
                    str(state.get("system_prompt", ""))
                ))
                # 估算历史消息
                history_tokens = sum(
                    estimate_tokens(
                        msg.content if hasattr(msg, "content") and isinstance(msg.content, str)
                        else str(getattr(msg, "content", ""))
                    )
                    for msg in messages
                )
                budget.track("history", history_tokens)
                runtime.context["cita_budget"] = budget

                if budget.status in (BudgetStatus.WARNING, BudgetStatus.CRITICAL):
                    logger.warning(
                        f"[Budget] {budget.status.value.upper()}: "
                        f"{budget.total_used}/{budget.total_budget} tokens "
                        f"({budget.usage_ratio:.0%})"
                    )
            except Exception as e:
                logger.debug(f"[Budget] 预算追踪跳过: {e}")

    # ==================== 动态工具裁剪 ====================

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], "Awaitable[ModelResponse]"],
    ):
        """异步版：根据 CITA 分析结果动态裁剪工具。

        所有异常兜底为「保留全部工具」，确保裁剪不影响主流程。
        """
        try:
            filtered = self._filter_tools_by_intent(request)
            if len(filtered) < len(request.tools):
                removed = [t.name if hasattr(t, 'name') else str(t)
                           for t in request.tools if t not in filtered]
                logger.info(
                    f"[middleware] 工具裁剪: {len(request.tools)} → {len(filtered)}, "
                    f"移除: {removed}"
                )
                request = request.override(tools=filtered)
        except Exception as e:
            logger.warning(f"[middleware] 工具裁剪失败，保留全部工具: {e}")
        return await handler(request)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ):
        """同步版：同 awrap_model_call。"""
        try:
            filtered = self._filter_tools_by_intent(request)
            if len(filtered) < len(request.tools):
                removed = [t.name if hasattr(t, 'name') else str(t)
                           for t in request.tools if t not in filtered]
                logger.info(
                    f"[middleware] 工具裁剪: {len(request.tools)} → {len(filtered)}, "
                    f"移除: {removed}"
                )
                request = request.override(tools=filtered)
        except Exception as e:
            logger.warning(f"[middleware] 工具裁剪失败，保留全部工具: {e}")
        return handler(request)

    @staticmethod
    def _filter_tools_by_intent(request: ModelRequest) -> list:
        """根据 CITA 语义分析结果，决定哪些工具需要发送。

        所有异常都会被捕获并降级为「保留全部工具」，确保工具裁剪永不影响主流程。
        """
        tools: list = request.tools
        try:
            return UnifiedMiddleware._do_filter_tools(tools, request)
        except Exception as e:
            logger.warning(f"[middleware] 工具裁剪异常，保留全部工具 ({len(tools)}个): {e}")
            return tools

    @staticmethod
    def _do_filter_tools(tools: list, request: ModelRequest) -> list:
        # ---- 安全获取 context ----
        ctx = None
        try:
            runtime = request.runtime
            if runtime is not None:
                ctx = runtime.context
        except Exception:
            pass

        if ctx is None:
            return tools  # 无 context → 保留全部

        # ---- 安全获取 CITA 分析 ----
        try:
            analysis = ctx.get("cita_analysis") if hasattr(ctx, "get") else None
        except Exception:
            return tools

        if analysis is None:
            return tools  # 无 CITA 分析 → 保留全部

        # ---- 构建需要的工具集合 ----
        needed: set[str] = set(_ALWAYS_TOOLS)

        # 实体检测
        try:
            entities = getattr(analysis, "entities", None) or []
            entity_types = set()
            for e in entities:
                try:
                    if hasattr(e, "type"):
                        entity_types.add(e.type)
                except Exception:
                    pass

            if "location" in entity_types or "weather" in entity_types:
                needed.update(_TOOL_DOMAIN_MAP["weather"])
            if "anime" in entity_types or "character" in entity_types:
                needed.update(_TOOL_DOMAIN_MAP["anime"])
        except Exception as e:
            logger.debug(f"[middleware] 实体检测跳过: {e}")

        # 意图标志检测
        try:
            if getattr(analysis, "needs_rag", False):
                needed.update(_TOOL_DOMAIN_MAP["knowledge"])
            if getattr(analysis, "needs_web_search", False):
                needed.update(_TOOL_DOMAIN_MAP["weather"])
        except Exception:
            pass

        # 意图类型检测
        try:
            primary_intent = getattr(analysis, "primary_intent", None) or ""
            if primary_intent in ("anime_search", "anime_recommendation", "season_anime"):
                needed.update(_TOOL_DOMAIN_MAP["anime"])
                needed.update(_TOOL_DOMAIN_MAP["knowledge"])
            elif primary_intent in ("weather", "location"):
                needed.update(_TOOL_DOMAIN_MAP["weather"])
            elif primary_intent in ("knowledge", "question_answering"):
                needed.update(_TOOL_DOMAIN_MAP["knowledge"])
        except Exception:
            pass

        # ---- 过滤工具 ----
        try:
            filtered = []
            for t in tools:
                try:
                    name = t.name if hasattr(t, "name") else (t.get("name") if isinstance(t, dict) else None)
                    if name and name in needed:
                        filtered.append(t)
                except Exception:
                    filtered.append(t)  # 无法获取名称的工具保留
        except Exception:
            return tools

        return filtered if filtered else tools

    # ==================== 动态 Prompt ====================

    def dynamic_prompt(self, request: ModelRequest) -> str:
        """使用 composer.py + Persona Engine 动态组装系统提示词。

        组装顺序: 用户画像 → 系统规则 → 世界观 → 角色灵魂 + 风格 → Skill → CITA

        Phase 4 增强（Persona Engine）：
        - 自动风格选择（情绪/话题感知）
        - 按需世界观检索（仅注入相关知识）
        - 动态语气指令（情绪自适应）
        - 角色切换过渡消息
        """
        ctx = request.runtime.context or {}
        persona_name: str | None = (
            ctx.get("persona") or request.state.get("persona")
        )
        if persona_name and persona_name.lower() == "none":
            persona_name = None

        is_report: bool = ctx.get("report", False)

        # Report 模式保持使用旧 prompt（独立场景）
        if is_report:
            base_prompt = load_report_prompts()
            logger.info(f"[middleware] Prompt: report 模式, 总长={len(base_prompt)} 字符")
            return base_prompt

        # 用户画像
        user_id = request.state.get("user_id")
        profile_context = build_profile_context(user_id) if user_id else ""

        # CITA 2.0 意图覆盖（优先使用 SemanticAnalysis）
        cita_overlay = ""
        cita_analysis = ctx.get("cita_analysis")
        cita_intent = ctx.get("cita_intent")

        # 提取 CITA 情绪和话题（用于 Persona Engine）
        user_emotions: list[str] = []
        cita_topic: str | None = None
        cita_entities: list = []

        if cita_analysis is not None and isinstance(cita_analysis, SemanticAnalysis):
            # CITA 2.0：使用增强 overlay（实体感知 + 多情绪 + 多意图协调）
            try:
                engine = SemanticEngine()
                cita_overlay = engine.build_overlay(cita_analysis)
            except Exception:
                cita_overlay = build_cita_overlay(cita_analysis)
            # 提取 Persona Engine 所需数据
            user_emotions = [
                s.emotion for s in cita_analysis.emotions
                if s.effective_intensity >= 0.3
            ]
            cita_entities = cita_analysis.entities
            # 话题推断
            if cita_analysis.needs_web_search:
                cita_topic = "weather"  # or other search topics
            elif cita_analysis.needs_rag:
                cita_topic = "tech_support"
            elif cita_analysis.primary_intent == "chitchat":
                cita_topic = "casual_chat"
                if user_emotions and user_emotions[0] in ("sad", "angry"):
                    cita_topic = "emotional_support"
            elif any(
                e.type == "anime" or e.type == "character"
                for e in cita_entities
            ):
                cita_topic = "anime_recommend"
        elif cita_intent is not None:
            # V1 兼容
            cita_overlay = build_cita_overlay(cita_intent)

        # ---- Phase 4: Persona Engine 增强 ----
        persona_style = ctx.get("style", "default")
        worldbook_text = ""
        tone_override = ""
        transition_msg = ctx.pop("_transition_msg", "")  # 取出并清除

        if persona_name:
            try:
                from agent.persona.engine import persona_engine as pe
                # 获取用户查询文本
                last_user_text = ""
                for msg in reversed(request.state.get("messages", [])):
                    if hasattr(msg, "content"):
                        content = msg.content
                        if isinstance(content, str) and content.strip():
                            last_user_text = content
                            break

                pe_result = pe.process(
                    persona=persona_name,
                    style=persona_style,
                    user_query=last_user_text,
                    user_emotions=user_emotions if user_emotions else None,
                    topic=cita_topic,
                    entities=cita_entities if cita_entities else None,
                )

                if pe_result.persona_prompt:
                    # Persona Engine 返回了完整角色提示词
                    # 使用它替代 composer 的角色部分
                    persona_prompt = pe_result.persona_prompt
                    worldbook_text = pe_result.worldbook_text
                    tone_override = pe_result.tone_override

                    # 更新 style 到 context（供下次使用）
                    if pe_result.style != persona_style:
                        ctx["style"] = pe_result.style
                        persona_style = pe_result.style

                    # 角色推荐
                    if pe_result.recommended_characters:
                        ctx["_recommended_chars"] = pe_result.recommended_characters

                    # 过渡消息
                    if pe_result.transition_msg:
                        transition_msg = pe_result.transition_msg
                        ctx["_transition_msg"] = transition_msg

                    logger.info(
                        f"[PersonaEngine] style={pe_result.style}, "
                        f"worldbook={pe_result.worldbook_entries}条, "
                        f"tone={pe_result.tone_instructions}条指令"
                    )
                else:
                    persona_prompt = ""  # 无角色模式
            except Exception as e:
                logger.warning(f"[PersonaEngine] 处理失败，回退到 composer: {e}")
                persona_prompt = ""  # 回退到 composer 加载
        else:
            persona_prompt = ""
            # 无角色时重置 style
            ctx.pop("style", None)

        # 获取 Skill 摘要（动态获取，保持每轮都有）
        skills_summary = ""
        try:
            from agent.skill_support import get_skill_registry
            registry = get_skill_registry()
            if registry.count > 0:
                skills_summary = registry.build_skills_summary()
        except Exception:
            pass

        # 使用 composer 组装（Persona Engine 提供增强的 persona_prompt）
        try:
            from prompts.composer import compose_prompt
            style = persona_style

            if persona_prompt:
                # Persona Engine 模式：用 PE 的角色提示词替代 composer 的角色部分
                # 组装：用户画像 → CITA → 系统规则 → PE角色提示词 → Skill
                parts: list[str] = []
                if profile_context:
                    parts.append(profile_context)
                if cita_overlay:
                    parts.append(f"## 当前对话上下文\n{cita_overlay}")
                if transition_msg:
                    parts.append(f"## 角色切换通知\n{transition_msg}")

                from prompts.composer import _load_system_base
                system_base = _load_system_base()
                if system_base:
                    parts.append(system_base)

                parts.append(persona_prompt)

                if skills_summary:
                    parts.append(
                        "## 可用 Skill（通过 invoke_skill 调用）\n"
                        "当用户任务匹配以下 Skill 时，先调 `invoke_skill(skill_name)` "
                        "获取详细指令，再按指令执行。\n\n"
                        f"{skills_summary}"
                    )

                base_prompt = "\n\n---\n\n".join(parts)
            else:
                # Composer 模式（无角色或 PE 不可用）
                base_prompt = compose_prompt(
                    persona=persona_name,
                    style=style,
                    skills_summary=skills_summary,
                    cita_overlay=cita_overlay,
                    user_profile=profile_context,
                )
        except Exception as e:
            logger.warning(f"[middleware] Composer 不可用，回退手动拼接: {e}")
            # Fallback: 手动拼接
            base_prompt = load_system_prompts()
            if profile_context:
                base_prompt = f"{profile_context}\n\n---\n\n{base_prompt}"
            if persona_name:
                persona_overlay = load_persona_overlay(persona_name)
                if persona_overlay:
                    base_prompt = (
                        f"你现在正在扮演角色「{persona_name}」，"
                        f"必须严格遵循以下人设进行对话：\n\n"
                        f"{persona_overlay}\n\n---\n\n## 工作指令\n\n{base_prompt}"
                    )
                if worldbook_text:
                    base_prompt = f"{worldbook_text}\n\n---\n\n{base_prompt}"
                if tone_override:
                    base_prompt = f"{base_prompt}\n\n---\n\n## 当前语气指令\n{tone_override}"
            if cita_overlay:
                base_prompt = f"## 当前对话上下文\n{cita_overlay}\n\n---\n\n{base_prompt}"

        # CITA 2.0 Token 预算更新
        cita_budget = ctx.get("cita_budget")
        if cita_budget is not None:
            try:
                from agent.cita.budget import estimate_tokens
                prompt_tokens = estimate_tokens(base_prompt)
                cita_budget.set_used("system_prompt", prompt_tokens)
                if persona_name:
                    persona_tokens = estimate_tokens(
                        persona_prompt if persona_prompt else ""
                    )
                    cita_budget.track("persona_overlay", persona_tokens)
                if skills_summary:
                    skill_tokens = estimate_tokens(skills_summary)
                    cita_budget.track("skill_instruction", skill_tokens)
            except Exception as e:
                logger.debug(f"[Budget] 更新跳过: {e}")

        # Phase 6: 结构化输出注入
        active_skill = ctx.get("_active_skill")
        if active_skill:
            try:
                from agent.structured_output.injector import inject_into_prompt
                injected = inject_into_prompt(base_prompt, active_skill)
                if injected != base_prompt:
                    base_prompt = injected
                    logger.info(
                        f"[middleware] 结构化输出注入: skill={active_skill}, "
                        f"增量={len(injected) - len(base_prompt)}字符"
                    )
            except Exception as e:
                logger.debug(f"[middleware] 结构化输出注入跳过: {e}")

        # 注入当前日期时间（让模型始终知道"现在是什么时候"）
        from datetime import datetime
        now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        weekday = ["一", "二", "三", "四", "五", "六", "日"][datetime.now().weekday()]
        time_context = (
            f"## 当前日期与时间（这是你的内置能力，无需工具）\n"
            f"今天是 {now_str}（星期{weekday}）。\n"
            "你有能力直接回答日期时间问题，因为系统已提供当前日期。\n"
            "当用户询问今天日期、几月几号、星期几、现在几点时，"
            "直接回答完整的年月日和星期，不要只说时间、不要拒绝。"
        )
        base_prompt = time_context + "\n\n" + base_prompt

        logger.info(
            f"[middleware] Prompt: persona={'PE-' + persona_name if persona_prompt else ('✓' if persona_name else '✗')}, "
            f"总长={len(base_prompt)} 字符"
        )
        return base_prompt
