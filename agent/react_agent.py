"""
ReAct Agent 主控制器
====================
基于 LangGraph 的 ReAct Agent，集成 Decision Engine 快/慢路由、
会话隔离存储、上下文自动裁剪，支持全链路异步流式输出。

每轮对话执行流程::

    session_store.get_history(session_id)   ← 加载本会话历史（内存）
        → trim_history(history)              ← 裁剪超限上下文
        → DecisionEngine.evaluate(query)     ← 快/慢路由判断
        → chat 路径: 直接 LLM 调用（无工具、低延迟）
        → agent 路径: create_agent_state → agent.astream (完整 ReAct)
        → session_store.append_pair(...)     ← 持久化本轮对话
        → chat_db.save_pair(...)             ← 持久化本轮对话（SQLite）

启动时恢复流程::

    chat_db.init_db()                        ← 自动建表
    chat_db.load_session_into_store(...)     ← SQLite → 内存恢复
"""

import asyncio
import os
import threading
import time
import uuid
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage, SystemMessage

from model.factory import chat_model
from utils.config_handler import agent_config
from utils.logger_handler import logger
from utils.prompt_loader import load_system_prompts
from memory.session_store import session_store
from memory.context_trimmer import trim_history, history_stats, estimate_tokens
from utils.conversation_tracer import ConversationTracer
from utils.performance_monitor import PerformanceMonitor
from observability.store import monitor_store
from memory.chat_db import chat_db
from agent.agent_state import create_agent_state
from agent.stream_events import TextChunk, ToolEvent, StructuredData
from agent.action_gate import action_gate
from agent.decision_engine import decision_engine
from memory.user_profile_extractor import extract_and_save_profile, build_profile_context
from agent.cita.semantic import SemanticEngine, SemanticAnalysis
from tools.agent_tools import (
    search_anime, fetch_anime, get_season_anime,
    rag_summarize, switch_persona, reset_persona,
    get_public_ip, get_current_time,
    maps_weather, maps_ip_location,
)
from tools.novel_tools import download_novel
from tools.mcp_client import mcp_manager
from tools.unified_middleware import UnifiedMiddleware
from skill_support import init_skills, get_skill_registry, SKILL_TOOLS

# 裁剪参数（从 agent.yaml 读取，可运行时调整）
_TRIM_CFG = agent_config.get("context", {})
TRIM_MAX_TOKENS = _TRIM_CFG.get("trim_max_tokens", 6000)
TRIM_MAX_ROUNDS = _TRIM_CFG.get("trim_max_rounds", 15)
LLM_TURN_TIMEOUT = float(_TRIM_CFG.get("llm_turn_timeout", 90))
TURN_QUEUE_TIMEOUT = float(_TRIM_CFG.get("turn_queue_timeout", 5))


def _usage_value(usage: dict, names: set[str]) -> int:
    """Read provider-specific cache fields from nested usage metadata."""
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key, value in usage.items():
        if key in names and isinstance(value, (int, float)):
            total += int(value)
        elif isinstance(value, dict):
            total += _usage_value(value, names)
    return total


def _cache_read_tokens(usage: dict) -> int:
    return _usage_value(usage, {"cache_read", "cache_read_input_tokens", "cached_tokens"})


def _cache_input_tokens(usage: dict) -> int:
    return _usage_value(usage, {"input_tokens", "prompt_tokens"})


def _has_usage_field(usage: dict, names: set[str]) -> bool:
    """Return whether a provider supplied any field from ``names``."""
    if not isinstance(usage, dict):
        return False
    for key, value in usage.items():
        if key in names and isinstance(value, (int, float)):
            return True
        if isinstance(value, dict) and _has_usage_field(value, names):
            return True
    return False


def _token_usage(message) -> dict[str, int | bool]:
    """Normalize token usage from LangChain and OpenAI-compatible messages."""
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict) or not usage:
        response_metadata = getattr(message, "response_metadata", {})
        if isinstance(response_metadata, dict):
            usage = response_metadata.get("token_usage") or response_metadata.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    cache_fields = {"cache_read", "cache_read_input_tokens", "cached_tokens"}
    input_tokens = _usage_value(
        usage,
        {"input_tokens", "prompt_tokens", "prompt_token_count"},
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": _usage_value(
            usage,
            {"output_tokens", "completion_tokens", "completion_token_count"},
        ),
        "total_tokens": _usage_value(usage, {"total_tokens", "total_token_count"}),
        "cache_read_tokens": _cache_read_tokens(usage),
        "cache_input_tokens": input_tokens,
        "cache_metrics_available": _has_usage_field(usage, cache_fields),
    }


class ReactAgent:
    """ReAct Agent，封装 LangGraph Agent 图的生命周期。

    支持：
    - 通过 ``default_persona`` 参数设置初始角色人设
    - 自动加载 / 裁剪 / 持久化会话历史
    - 多 session_id 完全隔离
    """

    def __init__(
        self,
        session_id: str = "default",
        user_id: str | None = None,
        default_persona: str | None = None,
    ):
        """
        Args:
            session_id:     会话唯一标识，用于区分不同用户/会话。
            user_id:        当前用户 ID（可选），报告生成场景使用。
            default_persona: 初始角色人设名称（可选），如 "Cyrene"。
                            None 表示默认专业客服。
        """
        self.session_id = session_id
        self.user_id = user_id
        self.default_persona = default_persona
        self._turn_lock = threading.Lock()
        self.performance_monitor = PerformanceMonitor()
        self.agent = None            # LangGraph 编译后的图
        self._initialized = False    # 是否已完成异步初始化
        self._turn_started_at = 0.0
        self._turn_snapshot_start = None
        self._current_tracer: ConversationTracer | None = None
        self._current_route = "unknown"
        self._current_outcome = "success"

    # ==================== 初始化 ====================

    async def init_agent(self):
        """异步初始化：拉取 MCP 远端工具并编译 Agent 图。

        MCP 连接失败时自动降级为仅本地工具，不阻塞 Agent 启动。
        """
        # 拉取 MCP 工具（天气/定位已改用高德 Web API 本地工具，仅 websearch 走 MCP）
        weather_mcp_tools = [maps_weather]
        if os.getenv("DASHSCOPE_API_KEY"):
            try:
                amap_tools = await mcp_manager.get_domain_tools("amap")
                if amap_tools:
                    weather_mcp_tools = amap_tools
                    print(f"[init_agent] DashScope AMap MCP tools loaded: {len(amap_tools)}")
            except Exception as e:
                print(f"[init_agent] AMap MCP failed, using local weather fallback: {e}")
        location_mcp_tools = [maps_ip_location]
        websearch_mcp_tools: list = []
        try:
            websearch_mcp_tools = await mcp_manager.get_domain_tools("websearch")
            print(f"[init_agent] WebSearch MCP 工具加载成功: websearch={len(websearch_mcp_tools)}")
        except Exception as e:
            print(f"[init_agent] ⚠️ WebSearch MCP 连接失败: {e}")

        local_tools = [
            search_anime, fetch_anime, get_season_anime,
            rag_summarize, switch_persona, reset_persona,
            get_public_ip, get_current_time,
            download_novel,
        ]
        # ---- Skill 工具 (invoke_skill / list_skills) ----
        skill_tools = list(SKILL_TOOLS)
        raw_tools = local_tools + skill_tools + weather_mcp_tools + location_mcp_tools + websearch_mcp_tools

        # ---- Action Gate: 过滤白名单/黑名单/危险工具 ----
        all_tools = action_gate.filter_tools(
            raw_tools,
            context={"user_id": self.user_id},
        )

        print("加载完成的全部工具：", [t.name for t in all_tools])

        # ---- 初始化 Skill 系统（异步文件扫描，不阻塞事件循环） ----
        try:
            await init_skills()
            skills_summary = get_skill_registry().build_skills_summary()
            print(f"[init_agent] Skill 系统已加载: {get_skill_registry().count} 个")
        except Exception as e:
            skills_summary = ""
            print(f"[init_agent] ⚠️ Skill 系统加载失败: {e}")

        # 构建 system prompt（注入 Skill 摘要）
        try:
            from prompts.composer import compose_base_prompt
            system_prompt = compose_base_prompt(skills_summary=skills_summary)
        except Exception:
            # Fallback: 旧架构
            base_prompt = load_system_prompts()
            if skills_summary:
                skill_section = (
                    f"\n\n## 可用 Skill（通过 invoke_skill 调用）\n"
                    f"当用户任务匹配以下 Skill 时，先调 `invoke_skill(skill_name)` "
                    f"获取详细指令，再按指令执行。\n\n{skills_summary}"
                )
                system_prompt = base_prompt + skill_section
            else:
                system_prompt = base_prompt

        self.agent = create_agent(
            model=chat_model,
            tools=all_tools,
            system_prompt=system_prompt,
            middleware=[UnifiedMiddleware()],
        )
        print(f"[init_agent] 统一中间件已激活: Gate + Policy + Timeout + CITA + Persona")

        # 持久化初始化：建表 + 从 SQLite 恢复历史到内存
        chat_db.init_db()
        chat_db.load_session_into_store(self.session_id, session_store)

        self._initialized = True

    # ==================== 消息提取 ====================

    @staticmethod
    def _extract_content(msg) -> str:
        """从 LangChain 消息对象中提取文本内容，兼容 list[dict] 格式。"""
        content = getattr(msg, "content", "")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(item["text"])
            content = "".join(text_parts)
        return content.strip() if content else ""

    @staticmethod
    def _extract_active_skill(messages: list) -> str | None:
        """从消息列表中提取当前激活的 Skill 名称。

        扫描 AIMessage 的 tool_calls，查找最近一次 ``invoke_skill`` 调用。
        """
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    if tc.get("name") == "invoke_skill":
                        return tc.get("args", {}).get("skill_name")
        return None

    @staticmethod
    async def _postprocess_structured(
        full_response: str,
        skill_name: str,
    ):
        """Phase 6: 结构化输出后处理。

        提取 JSON → Pydantic 校验 → 格式化 → 可选重试。
        返回 StructuredResult 或 None（非结构化 Skill / 校验失败）。
        """
        try:
            from agent.structured_output import process_structured_output
            from agent.structured_output.retry import retry_handler

            result = process_structured_output(full_response, skill_name=skill_name)
            if result is not None and result.valid:
                return result

            # 校验失败 → 尝试自动重试
            if result is not None and retry_handler.should_retry(result):
                logger.info(f"[结构化输出] 校验失败，尝试自动重试: skill={skill_name}")
                corrected = await retry_handler.retry_async(
                    full_response, result,
                    context={"skill": skill_name},
                )
                if corrected is not None and corrected.valid:
                    return corrected

            return None
        except Exception as e:
            logger.debug(f"[结构化输出] 后处理跳过: {e}")
            return None

    # ==================== Chat 路径（轻量，无工具） ====================

    async def _execute_chat(
        self, query: str, history: list, trace_id: str,
        tracer: "ConversationTracer | None" = None,
    ):
        """轻量 Chat 路径：直接 LLM 调用，无工具、无 ReAct 循环。

        相比 Agent 路径节省：
        - Tool schema token (~2000-3000/请求)
        - ReAct 思考步骤的延迟和 token
        - LangGraph 图编译开销

        CITA 2.0 + Persona Engine 增强：
        - 实体感知 + 多情绪安抚 + 多意图协调
        - 动态风格选择 + 世界观注入 + 语气指令

        Args:
            query: 用户输入文本。
            history: 裁剪后的历史消息列表。
            trace_id: 本轮唯一标识。
            tracer: 对话诊断追踪器（可选）。

        Yields:
            TextChunk: 文字片段（与 Agent 路径统一格式）。
        """
        from prompts.composer import compose_prompt, _load_system_base
        from agent.cita_classifier import classify_intent, build_cita_overlay

        # 构建轻量 system prompt（无 Skill 摘要，无工具规则的精简版）
        persona = self.default_persona
        profile_context = build_profile_context(self.user_id) if self.user_id else ""

        # CITA 2.0 语义分析（Chat 路径也享受增强分析）
        cita_overlay = ""
        analysis = None
        try:
            engine = SemanticEngine()
            analysis = engine.analyze(query)
            cita_overlay = engine.build_overlay(analysis)
            logger.debug(
                f"[trace={trace_id}] CITA 2.0 Chat: "
                f"entities={[(e.type, e.value) for e in analysis.entities]}, "
                f"emotions={[(s.emotion, f'{s.effective_intensity:.1f}') for s in analysis.emotions]}, "
                f"intents={[i.intent_type for i in analysis.intents]}"
            )
        except Exception:
            # 降级 V1
            try:
                intent = classify_intent(query)
                cita_overlay = build_cita_overlay(intent)
            except Exception:
                pass

        # ---- Phase 4: Persona Engine 增强 Chat 路径 ----
        user_emotions: list[str] = []
        cita_entities: list = []
        if analysis is not None:
            user_emotions = [
                s.emotion for s in analysis.emotions
                if s.effective_intensity >= 0.3
            ]
            cita_entities = analysis.entities

        persona_prompt = ""
        persona_style = "default"
        try:
            from agent.persona.engine import persona_engine as pe

            if persona:
                pe_result = pe.process(
                    persona=persona,
                    style="default",
                    user_query=query,
                    user_emotions=user_emotions if user_emotions else None,
                    topic="casual_chat",
                    entities=cita_entities if cita_entities else None,
                )
                if pe_result.persona_prompt:
                    persona_prompt = pe_result.persona_prompt
                    persona_style = pe_result.style
        except Exception as e:
            logger.debug(f"[trace={trace_id}] PersonaEngine Chat 跳过: {e}")

        if persona_prompt:
            # Persona Engine 组装模式
            parts: list[str] = []
            if profile_context:
                parts.append(profile_context)
            if cita_overlay:
                parts.append(f"## 当前对话上下文\n{cita_overlay}")

            system_base = _load_system_base()
            if system_base:
                parts.append(system_base)

            parts.append(persona_prompt)

            parts.append(
                "## 当前模式：闲聊陪伴\n"
                "用户正在进行社交闲聊，请友好、温暖、简短地回应。"
                "不需要调用工具、不需要检索知识库、不需要展开复杂分析。"
                "像朋友一样自然地聊天。"
            )
            system_prompt = "\n\n---\n\n".join(parts)
        else:
            # Composer 模式（无角色或 PE 不可用）
            system_prompt = compose_prompt(
                persona=persona,
                style=persona_style,
                skills_summary="",  # Chat 路径不需要 Skill
                cita_overlay=cita_overlay,
                user_profile=profile_context,
            )

            # 追加 Chat 模式专用指令
            chat_instruction = (
                "\n\n---\n\n## 当前模式：闲聊陪伴\n"
                "用户正在进行社交闲聊，请友好、温暖、简短地回应。"
                "不需要调用工具、不需要检索知识库、不需要展开复杂分析。"
                "像朋友一样自然地聊天。"
            )
            system_prompt += chat_instruction

        # 注入当前日期时间（让 Chat 路径的模型也能知道"现在是什么时候"）
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
        system_prompt = time_context + "\n\n" + system_prompt

        # 构建消息列表
        messages = [SystemMessage(content=system_prompt)]
        for msg in history:
            messages.append(msg)
        messages.append(HumanMessage(content=query))

        # 直接 LLM 流式调用（无工具）
        response_chunks: list[str] = []
        llm_started_at = time.perf_counter()
        usage_totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_input_tokens": 0,
            "cache_metrics_available": False,
        }
        try:
            async for chunk in chat_model.astream(messages):
                content = self._extract_content(chunk)
                usage = _token_usage(chunk)
                usage_totals["input_tokens"] += usage["input_tokens"]
                usage_totals["output_tokens"] += usage["output_tokens"]
                usage_totals["cache_read_tokens"] += usage["cache_read_tokens"]
                usage_totals["cache_input_tokens"] += usage["cache_input_tokens"]
                usage_totals["cache_metrics_available"] = (
                    usage_totals["cache_metrics_available"] or usage["cache_metrics_available"]
                )
                if content:
                    response_chunks.append(content)
                    yield TextChunk(content=content)
            self.performance_monitor.record_llm_call(
                time.perf_counter() - llm_started_at,
                **usage_totals,
            )
        except Exception as e:
            self._current_outcome = "error"
            if tracer:
                error_text = f"{type(e).__name__}: {e}"
                tracer.fail(error_text)
                tracer.exit(error=error_text)
            logger.error(f"[trace={trace_id}] Chat 路径异常: {e}", exc_info=True)
            yield TextChunk(content=f"\n\n⚠️ 处理请求时发生错误（{type(e).__name__}），请重试。")
            return

        # 持久化
        full_response = "".join(response_chunks)
        if tracer:
            tracer.chat_path_done(len(full_response))
        logger.info(
            f"[trace={trace_id}] Chat 完成: "
            f"响应长度={len(full_response)}"
        )

        # Phase 6: 结构化输出后处理
        active_skill = self._extract_active_skill(messages)
        if active_skill and full_response:
            struct_result = await self._postprocess_structured(full_response, active_skill)
            if struct_result is not None:
                yield StructuredData(
                    schema_type=struct_result.schema_type,
                    model=struct_result.model,
                    formatted=struct_result.formatted,
                    raw_json=struct_result.raw_json,
                )

        if full_response:
            session_store.append_pair(self.session_id, query, full_response)
            chat_db.save_pair(self.session_id, query, full_response)
            if tracer:
                tracer.persist(
                    session_store.history_length(self.session_id),
                    chat_db.session_message_count(self.session_id),
                )

            # 会话元数据更新
            msg_count = session_store.history_length(self.session_id)
            meta = chat_db.get_session_meta(self.session_id)
            chat_db.upsert_session_meta(
                self.session_id,
                user_id=self.user_id or "",
                message_count=msg_count,
                title=meta.get("title") if meta else None,
            )

            # 会话标题自动生成
            if meta is None or not meta.get("title"):
                self._save_title_from_query(query)

            # 用户画像提取（异步后台）
            if self.user_id:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        extract_and_save_profile(self.user_id, query, full_response)
                    )
                except RuntimeError:
                    pass

    # ==================== 会话管理 ====================

    def clear_history(self):
        """清空当前会话的全部历史记录（内存 + SQLite）。"""
        session_store.clear(self.session_id)
        chat_db.clear_session(self.session_id)

    def get_history_info(self) -> dict:
        """返回当前会话历史的统计摘要（供 UI 展示）。"""
        raw = session_store.get_history(self.session_id)
        stats = history_stats(raw)
        token = getattr(self, "_total_token_stats", {})
        last = getattr(self, "_last_turn_tokens", {})
        decision_stats = decision_engine.get_stats(self.session_id)
        return {
            "session_id": self.session_id,
            "message_count": stats["total_messages"],
            "round_count": stats["total_rounds"],
            "estimated_tokens": stats["estimated_tokens"],
            "llm_input_tokens": token.get("input_tokens", 0),
            "llm_output_tokens": token.get("output_tokens", 0),
            "llm_total_tokens": token.get("total_tokens", 0),
            "last_turn_tokens": last.get("total_tokens", 0),
            # Decision Engine 统计
            "decision_chat_count": decision_stats.get("chat", 0),
            "decision_agent_count": decision_stats.get("agent", 0),
            "decision_chat_ratio": decision_stats.get("chat_ratio", 0),
            "performance": self.performance_monitor.snapshot(),
        }

    def get_last_turn_observation(self) -> dict:
        """返回最近一轮的路由和追踪标识，供评测或接口使用。"""
        return {
            "trace_id": self._current_tracer.trace_id if self._current_tracer else "",
            "route": self._current_route,
            "outcome": self._current_outcome,
        }

    def _enqueue_turn_observation(self) -> None:
        """将本轮追踪与增量指标交给后台监控存储。"""
        tracer = self._current_tracer
        baseline = self._turn_snapshot_start
        if tracer is None or baseline is None:
            return

        current = self.performance_monitor.snapshot()
        visible_tokens = current.visible_output_tokens - baseline.visible_output_tokens
        monitor_store.enqueue_turn(
            {
                "trace_id": tracer.trace_id,
                "session_id": self.session_id,
                "route": self._current_route,
                "outcome": self._current_outcome,
                "duration_ms": round((time.perf_counter() - self._turn_started_at) * 1000, 2),
                "ttft_ms": (
                    round(current.ttft_seconds * 1000, 2)
                    if visible_tokens > 0 and current.ttft_seconds is not None
                    else None
                ),
                "input_tokens": current.input_tokens - baseline.input_tokens,
                "output_tokens": current.output_tokens - baseline.output_tokens,
                "tool_calls": current.tool_calls - baseline.tool_calls,
                "error_type": "" if self._current_outcome == "success" else self._current_outcome,
                "events": tracer.export_events(),
            }
        )

    # ==================== 核心执行 ====================

    async def execute_stream_async(self, query: str):
        """Run one turn at a time for each conversation session."""
        acquired = await asyncio.to_thread(
            self._turn_lock.acquire, True, TURN_QUEUE_TIMEOUT
        )
        if not acquired:
            logger.warning("[ReactAgent] Overlapping request rejected")
            self.performance_monitor.record_rejection()
            yield TextChunk(content="\n\n正在处理上一条消息，请等待其完成后再发送。")
            return

        try:
            self._turn_started_at = time.perf_counter()
            self._turn_snapshot_start = self.performance_monitor.snapshot()
            self._current_tracer = None
            self._current_route = "unknown"
            self._current_outcome = "success"
            self.performance_monitor.start_turn()
            async with asyncio.timeout(LLM_TURN_TIMEOUT):
                async for event in self._execute_stream_locked(query):
                    if isinstance(event, TextChunk):
                        self.performance_monitor.record_visible_text(
                            estimate_tokens(event.content)
                        )
                    yield event
        except TimeoutError:
            self._current_outcome = "timeout"
            if self._current_tracer:
                self._current_tracer.fail("TimeoutError: turn timeout")
                self._current_tracer.exit()
            logger.warning("[ReactAgent] Turn timed out after %.0f seconds", LLM_TURN_TIMEOUT)
            yield TextChunk(content="\n\n请求超时，请稍后重试。")
        except Exception as error:
            self._current_outcome = "error"
            if self._current_tracer:
                self._current_tracer.fail(f"{type(error).__name__}: {error}")
                self._current_tracer.exit()
            logger.error("[ReactAgent] Turn failed: %s", error, exc_info=True)
            yield TextChunk(content="\n\n⚠️ 处理请求时发生错误，请重试。")
        finally:
            self.performance_monitor.finish_turn(self._current_outcome)
            self._enqueue_turn_observation()
            self._turn_lock.release()

    async def _execute_stream_locked(self, query: str):
        """
        异步流式执行，产出结构化事件（TextChunk | ToolEvent）。

        每轮执行前自动加载并裁剪会话历史，执行后持久化本轮对话。

        Args:
            query: 用户输入文本。

        Yields:
            TextChunk: 文字片段（思考 / 回答）。
            ToolEvent:  工具调用事件（开始 / 结束）。
        """
        if not self._initialized:
            await self.init_agent()

        # ---- trace_id: 本轮对话唯一标识 ----
        trace_id = str(uuid.uuid4())[:8]
        tracer = ConversationTracer(session_id=self.session_id, trace_id=trace_id)
        self._current_tracer = tracer
        tracer.enter(query)

        # ---- 1) 加载并裁剪历史消息 ----
        raw_history = session_store.get_history(self.session_id)
        tracer.load_history(raw_history)

        trimmed_history = trim_history(
            raw_history,
            max_tokens=TRIM_MAX_TOKENS,
            max_rounds=TRIM_MAX_ROUNDS,
        )
        tracer.after_trim(raw_history, trimmed_history)

        # ---- 2) Decision Engine 快/慢路由 ----
        decision = decision_engine.evaluate(
            query,
            session_id=self.session_id,
            history=trimmed_history,
        )
        tracer.decision(decision.route, decision.confidence, decision.reason)
        self._current_route = decision.route
        logger.info(
            f"[trace={trace_id}] Decision: route={decision.route} "
            f"conf={decision.confidence:.2f} reason={decision.reason}"
        )

        # ---- 2a) Chat 路径：直接 LLM，无工具 ----
        if decision.is_chat:
            tracer.chat_path_start(len(trimmed_history))
            async for event in self._execute_chat(query, trimmed_history, trace_id, tracer):
                yield event
            tracer.exit()
            return

        # ---- 2b) Agent 路径：完整 ReAct Agent（原有流程） ----
        state = create_agent_state(
            user_query=query,
            session_id=self.session_id,
            user_id=self.user_id,
            persona=self.default_persona,
            history=trimmed_history,
        )
        tracer.agent_path_start(len(state["messages"]))
        tracer.agent_model_before(len(state["messages"]))

        # ---- 3) 流式执行 + 事件分类 ----
        response_chunks: list[str] = []
        token_stats = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        last_graph_event_at = time.perf_counter()
        try:
            async for chunk in self.agent.astream(state, stream_mode="values"):
                now = time.perf_counter()
                latest_msg = chunk["messages"][-1]

                # —— AI 消息：可能含 tool_calls 和/或 文本 ——
                if isinstance(latest_msg, AIMessage):
                    # 3a) 工具调用事件
                    if latest_msg.tool_calls:
                        self.performance_monitor.record_step(len(latest_msg.tool_calls))
                        for tc in latest_msg.tool_calls:
                            tracer.agent_tool_call(tc["name"])
                            logger.info(f"[trace={trace_id}] 调用工具: {tc['name']}")
                            yield ToolEvent(
                                phase="start",
                                tool_name=tc["name"],
                                tool_args=tc.get("args", {}),
                            )

                    # 3b) Token 统计（从 usage_metadata 提取）
                    usage = _token_usage(latest_msg)
                    self.performance_monitor.record_llm_call(
                        now - last_graph_event_at,
                        usage["input_tokens"],
                        usage["output_tokens"],
                        usage["cache_read_tokens"],
                        usage["cache_input_tokens"],
                        usage["cache_metrics_available"],
                    )
                    token_stats["input_tokens"] += usage["input_tokens"]
                    token_stats["output_tokens"] += usage["output_tokens"]
                    token_stats["total_tokens"] += usage["total_tokens"]

                    # 3c) 文字内容
                    content = self._extract_content(latest_msg)
                    if content:
                        response_chunks.append(content)
                        yield TextChunk(content=content)

                # —— Tool 消息：工具返回结果 ——
                elif isinstance(latest_msg, ToolMessage):
                    result_text = self._extract_content(latest_msg)
                    self.performance_monitor.record_tool_call(
                        now - last_graph_event_at,
                        success=not result_text.startswith("[工具调用被拒绝]"),
                    )
                    tool_name = getattr(latest_msg, "name", "unknown")
                    tracer.agent_tool_done(tool_name, len(result_text))
                    yield ToolEvent(
                        phase="end",
                        tool_name=tool_name,
                        result_preview=(
                            result_text[:200] + "…" if len(result_text) > 200
                            else result_text
                        ),
                    )

                last_graph_event_at = now

            # ---- 4) 持久化本轮对话（内存 + SQLite 双写） ----
            full_response = "".join(response_chunks)
            tracer.agent_path_done(len(full_response), token_stats)
            logger.info(
                f"[trace={trace_id}] 完成: tokens={token_stats}, "
                f"响应长度={len(full_response)}"
            )

            # Phase 6: 结构化输出后处理
            active_skill = self._extract_active_skill(state["messages"])
            if active_skill and full_response:
                struct_result = await self._postprocess_structured(full_response, active_skill)
                if struct_result is not None:
                    yield StructuredData(
                        schema_type=struct_result.schema_type,
                        model=struct_result.model,
                        formatted=struct_result.formatted,
                        raw_json=struct_result.raw_json,
                    )

            if full_response:
                session_store.append_pair(self.session_id, query, full_response)
                chat_db.save_pair(self.session_id, query, full_response)
                tracer.persist(
                    session_store.history_length(self.session_id),
                    chat_db.session_message_count(self.session_id),
                )

                # ---- 4a) 更新会话元数据（消息计数） ----
                msg_count = session_store.history_length(self.session_id)
                meta = chat_db.get_session_meta(self.session_id)
                if meta is None:
                    chat_db.upsert_session_meta(
                        self.session_id,
                        user_id=self.user_id or "",
                        message_count=msg_count,
                    )
                else:
                    chat_db.upsert_session_meta(
                        self.session_id, message_count=msg_count,
                    )

                # ---- 4b) Token 统计累积 ----
                if not hasattr(self, "_total_token_stats"):
                    self._total_token_stats = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                for k in token_stats:
                    self._total_token_stats[k] = self._total_token_stats.get(k, 0) + token_stats[k]
                self._last_turn_tokens = token_stats

                # ---- 4c) 会话标题自动生成（首次对话后，同步） ----
                if meta is None or not meta.get("title"):
                    self._save_title_from_query(query)

                # ---- 4c) 用户画像提取（异步，不阻塞） ----
                if self.user_id:
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            extract_and_save_profile(
                                self.user_id, query, full_response
                            )
                        )
                    except RuntimeError:
                        pass  # 不在 async 上下文中，跳过（非 Streamlit 环境）

            tracer.exit()  # Agent 路径成功退出

        except Exception as e:
            self._current_outcome = "error"
            tracer.exit(error=f"{type(e).__name__}: {e}")
            logger.error(
                f"[ReactAgent] 流式执行异常: {type(e).__name__}: {e}",
                exc_info=True,
            )
            yield TextChunk(content=f"\n\n⚠️ 处理请求时发生错误（{type(e).__name__}），请重试。")

    def _save_title_from_query(self, first_query: str) -> None:
        """Save a useful local title without making another model request."""
        title = " ".join(first_query.strip().split())[:30]
        if title:
            chat_db.upsert_session_meta(self.session_id, title=title)

    def _generate_title_async(self, first_query: str):
        """异步生成会话标题（基于第一条用户消息）。"""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._generate_session_title(first_query))
        except RuntimeError:
            logger.debug("[ReactAgent] 标题生成跳过：不在 async 上下文中")

    async def _generate_session_title(self, first_query: str):
        """调用 LLM 生成会话标题。"""
        prompt = (
            f"为以下对话起一个简短的标题（不超过15个字），"
            f"直接输出标题文本，不要加引号或额外说明。\n"
            f"用户第一条消息：{first_query[:200]}"
        )
        try:
            response = await chat_model.ainvoke(prompt)
            title = (
                response.content if hasattr(response, "content")
                else str(response)
            ).strip().replace('"', '').replace("'", "")
            title = title[:30]  # 限制长度
            chat_db.upsert_session_meta(self.session_id, title=title)
            logger.info(f"[ReactAgent] 会话标题: {title}")
        except Exception as e:
            logger.warning(f"[ReactAgent] 标题生成失败: {e}")

    # ==================== 同步包装器（供 Streamlit 调用） ====================

    def execute_stream(self, query: str):
        """
        同步流式接口，yield 结构化事件（TextChunk | ToolEvent）。

        用于 Streamlit 这类同步框架中直接调用，无需手动管理事件循环。

        使用后台线程 + asyncio.run() 确保所有异步操作在同一个
        事件循环中完成，避免 httpx.AsyncClient 跨循环错乱导致挂死。
        """
        import queue
        import threading

        result_queue: queue.Queue = queue.Queue()

        async def _run() -> None:
            try:
                async for event in self.execute_stream_async(query):
                    result_queue.put(("event", event))
            except Exception as e:
                result_queue.put(("error", e))
            finally:
                result_queue.put(("done", None))

        def _target() -> None:
            asyncio.run(_run())

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()

        while True:
            try:
                kind, value = result_queue.get(timeout=300)
            except queue.Empty:
                yield TextChunk(content="\n\n⚠️ 请求超时（300s），请重试。")
                break

            if kind == "done":
                break
            elif kind == "error":
                logger.error(
                    f"[ReactAgent] 流式执行异常: {type(value).__name__}: {value}",
                    exc_info=True,
                )
                yield TextChunk(content=f"\n\n⚠️ 处理请求时发生错误（{type(value).__name__}），请重试。")
                break
            else:
                yield value

        thread.join(timeout=5)

    def execute_stream_text(self, query: str):
        """
        向后兼容的纯文本流式接口。

        仅产出 TextChunk 的 content 字符串，
        ToolEvent 被跳过（适合不需要工具日志的旧版 UI）。
        """
        for event in self.execute_stream(query):
            if isinstance(event, TextChunk):
                yield event.content


# ==================== 入口 ====================

def _ensure_init():
    """为 app.py 提供同步初始化入口（Streamlit 启动时调用一次）。"""
    agent = ReactAgent()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(agent.init_agent())
    finally:
        loop.close()
    return agent


async def main():
    """命令行测试入口。"""
    agent = ReactAgent(session_id="test_session")
    await agent.init_agent()
    async for res in agent.execute_stream_async("查询我当地的实时气温"):
        print(res)


if __name__ == '__main__':
    asyncio.run(main())
