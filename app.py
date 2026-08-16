"""
MutiRoleAgent —— Streamlit 前端入口
==========================================
基于 ReAct Agent + RAG + MCP 的扫拖机器人专业客服系统。
支持多会话隔离、历史上下文自动裁剪、角色人设动态切换。
"""

import asyncio
import os
import time
import uuid
from datetime import datetime, date

import streamlit as st
from agent.react_agent import ReactAgent
from agent.stream_events import TextChunk, ToolEvent, StructuredData, get_tool_display_name
from channels.manager import agent_cache
from memory.chat_db import chat_db
from agent.knowledge_base import KnowledgeBaseService
from utils.path_tool import get_abs_path
from utils.file_handler import txt_loader, pdf_loader, json_loader
from utils.persona_loader import persona_loader
from utils.logger_handler import logger

# ==================== 页面配置 ====================
st.set_page_config(
    page_title="MutiRoleAgent",
    page_icon="🤖",
    layout="wide",
)

# ==================== 会话状态初始化 ====================

def _init_agent_sync(session_id: str, user_id: str | None = None, default_persona: str | None = None) -> ReactAgent:
    """在 Streamlit 启动时同步完成 Agent 异步初始化。

    优先从跨 channel 共享的 ``agent_cache`` 获取，缓存未命中时才创建新实例。
    """
    # 快速路径：缓存命中
    cached = agent_cache.get(session_id)
    if cached is not None:
        # 如果 user_id / persona 变化，淘汰旧缓存
        if (user_id and cached.user_id != user_id) or \
           (default_persona and cached.default_persona != default_persona):
            agent_cache.evict(session_id)
        else:
            return cached

    agent = ReactAgent(session_id=session_id, user_id=user_id, default_persona=default_persona)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(agent.init_agent())
    finally:
        loop.close()
    agent_cache.put(session_id, agent)
    return agent


# session_id 持久化到 URL 参数，刷新页面不丢失
# 优先级: query_params（URL） > st.session_state（内存） > SQLite 最近会话 > 新建
if "session_id" in st.query_params:
    st.session_state["session_id"] = st.query_params["session_id"]
elif "session_id" not in st.session_state:
    # 尝试恢复最近一次会话
    try:
        recent_sessions = chat_db.list_sessions_with_meta(limit=1)
        if recent_sessions and chat_db.session_message_count(recent_sessions[0]["session_id"]) > 0:
            restored_id = recent_sessions[0]["session_id"]
            st.session_state["session_id"] = restored_id
            st.query_params["session_id"] = restored_id
        else:
            raise Exception("无历史会话")
    except Exception:
        new_id = str(uuid.uuid4())
        st.session_state["session_id"] = new_id
        st.query_params["session_id"] = new_id

# 预加载角色卡列表
PERSONA_NAMES = ["（无）"] + persona_loader.available_names

if "user_id" not in st.session_state:
    st.session_state["user_id"] = None

# 默认角色人设：昔涟（Cyrene）
if "persona" not in st.session_state:
    st.session_state["persona"] = "Cyrene"

if "agent" not in st.session_state:
    with st.spinner("正在初始化 Agent（加载 MCP 工具 + RAG 知识库）……"):
        st.session_state["agent"] = _init_agent_sync(
            st.session_state["session_id"],
            st.session_state["user_id"],
            st.session_state["persona"],
        )
    st.success("Agent 初始化完成！")

if "message" not in st.session_state:
    st.session_state["message"] = []

if "kb_service" not in st.session_state:
    st.session_state["kb_service"] = KnowledgeBaseService()

# 便捷引用
agent: ReactAgent = st.session_state["agent"]

# 如果 UI 消息列表为空但 SQLite 有历史，从数据库恢复
if not st.session_state["message"] and agent.session_id:
    try:
        raw_history = chat_db.get_history_raw(agent.session_id)
        if raw_history:
            st.session_state["message"] = [
                {"role": row["role"], "content": row["content"]}
                for row in raw_history
            ]
            logger.info(f"[app] 从 SQLite 恢复 {len(raw_history)} 条消息: session={agent.session_id[:16]}…")
    except Exception as e:
        logger.warning(f"[app] 恢复历史消息失败: {e}")

# ==================== 侧边栏 —— 会话管理 ====================

with st.sidebar:
    st.header("📋 会话信息")

    info = agent.get_history_info()
    current_sid = st.session_state["session_id"]
    current_uid = st.session_state.get("user_id")

    # ---- 用户 ID ----
    user_id_input = st.text_input(
        "👤 用户 ID", value=current_uid or "",
        placeholder="输入你的用户 ID（如 1001）…",
        help="用于关联使用记录和长期记忆。",
    )
    if user_id_input != (current_uid or ""):
        if user_id_input.strip():
            st.session_state["user_id"] = user_id_input.strip()
        else:
            st.session_state["user_id"] = None
        # 重建 agent 以应用新的 user_id
        st.session_state["agent"] = _init_agent_sync(
            current_sid, st.session_state["user_id"],
            st.session_state["persona"],
        )
        st.rerun()

    # ---- 角色人设 ----
    persona_display = {
        "（无）": "（无）",
        "Cyrene": "🌸 昔涟",
        "Columbina": "🕊️ 哥伦比亚",
        "Ye Shunguang": "✨ 叶瞬光",
        "Zhuang Fangyi": "🌿 庄方宜",
    }
    current_persona = st.session_state.get("persona", "Cyrene")
    selected_label = persona_display.get(current_persona, current_persona)
    selected_persona = st.selectbox(
        "🎭 角色人设",
        options=list(persona_display.keys()),
        format_func=lambda k: persona_display.get(k, k),
        index=list(persona_display.keys()).index(current_persona)
            if current_persona in persona_display else 0,
        help="切换 AI 的角色人设和语气风格。",
    )
    if selected_persona != current_persona:
        new_persona = selected_persona if selected_persona != "（无）" else None
        st.session_state["persona"] = new_persona
        st.session_state["agent"] = _init_agent_sync(
            current_sid, current_uid,
            default_persona=new_persona,
        )
        st.rerun()

    # 显示完整会话 ID（可复制）
    meta = chat_db.get_session_meta(current_sid)
    title = meta["title"] if meta and meta.get("title") else "（新会话）"
    st.caption(f"📝 标题: **{title}**")
    st.caption(f"🆔 ID: `{current_sid[:20]}…`")
    st.metric("消息数", info["message_count"])
    st.metric("对话轮数", info["round_count"])
    st.metric("上下文 Token（估算）", info["estimated_tokens"])
    if info.get("llm_total_tokens", 0) > 0:
        st.metric("LLM 消耗 Token", info["llm_total_tokens"])
    if info.get("last_turn_tokens", 0) > 0:
        st.caption(f"上轮消耗: {info['last_turn_tokens']} tokens")
    performance = info.get("performance")
    if performance is not None:
        cache_text = (
            f"{performance.cache_hit_rate:.0%}"
            if performance.cache_hit_rate is not None
            else "N/A"
        )
        ttft_text = (
            f"{performance.ttft_seconds:.2f}s"
            if performance.ttft_seconds is not None
            else "N/A"
        )
        st.caption(
            "Agent 性能\n"
            f"{performance.task_rounds} 轮 · {performance.execution_steps} 步 | "
            f"LLM {performance.llm_duration_seconds:.1f}s · "
            f"工具调用 {performance.tool_duration_seconds:.1f}s |\n"
            f"首 token 平均 {ttft_text} · "
            f"输出 {performance.output_tokens_per_second:.1f} tok/s |\n"
            f"缓存命中 {cache_text} |\n"
            f"输入 {performance.input_tokens:,} tok · "
            f"输出 {performance.output_tokens:,} tok"
        )

    st.divider()

    # ---- 新建会话 ----
    if st.button("🆕 新建会话", use_container_width=True):
        new_id = str(uuid.uuid4())
        st.session_state["session_id"] = new_id
        st.query_params["session_id"] = new_id
        st.session_state["agent"] = _init_agent_sync(
            new_id, st.session_state["user_id"],
            st.session_state["persona"],
        )
        st.session_state["message"] = []
        st.rerun()

    # ---- 切换到已有会话 ----
    st.caption("输入会话 ID 可恢复历史对话：")
    switch_to = st.text_input(
        "切换会话", placeholder="粘贴会话 ID…",
        label_visibility="collapsed",
    )
    if switch_to and switch_to != current_sid:
        st.session_state["session_id"] = switch_to
        st.query_params["session_id"] = switch_to
        st.session_state["agent"] = _init_agent_sync(
            switch_to, st.session_state["user_id"],
            st.session_state["persona"],
        )
        st.session_state["message"] = []
        st.rerun()

    st.divider()

    if st.button("🗑️ 清空对话历史", use_container_width=True):
        agent.clear_history()
        agent_cache.evict(current_sid)
        st.session_state["message"] = []
        st.rerun()

    st.divider()

    # SQLite 持久化状态
    try:
        db_sessions = chat_db.total_sessions()
        db_msgs = chat_db.session_message_count(current_sid)
        st.caption(f"💾 数据库共 {db_sessions} 个会话")
        if db_msgs > 0:
            st.caption(f"当前会话 {db_msgs} 条消息。")
        else:
            st.caption("当前会话暂无历史记录。")
    except Exception as e:
        logger.warning(f"[app] SQLite 状态读取失败: {e}")
        st.caption("⚠️ SQLite 持久化未就绪")

    # ---- 历史会话列表（点击切换 / 删除） ----
    st.divider()
    st.caption("📜 历史会话")
    try:
        sessions = chat_db.list_sessions_with_meta(limit=15)
        if sessions:
            for s in sessions:
                sid = s["session_id"]
                is_current = sid == current_sid
                stitle = s["title"] or "（无标题）"
                count = s["message_count"]
                c1, c2 = st.columns([4, 1])
                with c1:
                    label = f"{'👉 ' if is_current else ''}{stitle[:15]} ({count}条)"
                    if not is_current:
                        if st.button(label, key=f"sw_{sid}", use_container_width=True):
                            st.session_state["session_id"] = sid
                            st.query_params["session_id"] = sid
                            st.session_state["agent"] = _init_agent_sync(
                                sid, current_uid, st.session_state.get("persona"),
                            )
                            st.session_state["message"] = []
                            st.rerun()
                    else:
                        st.info(label)
                with c2:
                    if st.button("🗑", key=f"del_{sid}", help=f"删除会话 {stitle}"):
                        chat_db.clear_session(sid)
                        agent_cache.evict(sid)
                        if is_current:
                            # 删除当前会话 → 切到最近一个或新建
                            remaining = chat_db.list_sessions_with_meta(limit=1)
                            if remaining:
                                new_sid = remaining[0]["session_id"]
                            else:
                                new_sid = str(uuid.uuid4())
                            st.session_state["session_id"] = new_sid
                            st.query_params["session_id"] = new_sid
                            st.session_state["agent"] = _init_agent_sync(
                                new_sid, current_uid, st.session_state.get("persona"),
                            )
                        st.session_state["message"] = []
                        st.rerun()
        else:
            st.caption("暂无历史会话")
    except Exception as e:
        logger.warning(f"[app] 历史会话列表读取失败: {e}")
        st.caption("⚠️ 无法读取历史会话")

    st.divider()

    # ==================== 知识库更新 ====================
    st.header("📁 知识库更新")

    uploaded_file = st.file_uploader(
        "上传 TXT / PDF / JSON 文件到知识库",
        type=["txt", "pdf", "json"],
        accept_multiple_files=False,
    )

    if uploaded_file is not None:
        file_name = uploaded_file.name
        file_size = uploaded_file.size / 1024
        file_ext = os.path.splitext(file_name)[1].lower()

        st.caption(f"文件名: {file_name}")
        st.caption(f"大小: {file_size:.2f} KB")

        # 1) 保存到 data 目录
        file_bytes = uploaded_file.getvalue()
        data_dir = get_abs_path("data")
        os.makedirs(data_dir, exist_ok=True)
        save_path = os.path.join(data_dir, file_name)
        with open(save_path, "wb") as f:
            f.write(file_bytes)
        st.caption(f"已保存到: data/{file_name}")

        # 2) 提取文本
        if file_ext == ".txt":
            try:
                docs = txt_loader(save_path)
                text = "\n".join(d.page_content for d in docs)
                if not text.strip():
                    st.error("TXT 文件内容为空")
                    st.stop()
            except Exception as e:
                st.error(f"TXT 解析失败: {e}")
                st.stop()
        elif file_ext == ".pdf":
            try:
                docs = pdf_loader(save_path)
                text = "\n".join(d.page_content for d in docs)
                if not text.strip():
                    st.error("PDF 无法提取文本（可能是扫描件或图片 PDF）")
                    st.stop()
            except Exception as e:
                st.error(f"PDF 解析失败: {e}")
                st.stop()
        elif file_ext == ".json":
            try:
                docs = json_loader(save_path)
                text = "\n".join(d.page_content for d in docs)
                if not text.strip():
                    st.error("JSON 解析后无有效内容")
                    st.stop()
            except Exception as e:
                st.error(f"JSON 解析失败: {e}")
                st.stop()
        else:
            st.error(f"不支持的文件格式: {file_ext}")
            st.stop()

        # 3) 向量入库
        with st.spinner("载入知识库中…"):
            result = st.session_state["kb_service"].upload_by_str(text, file_name)
            if "[成功]" in result:
                st.success(result)
            elif "[跳过]" in result:
                st.info(result)
            else:
                st.warning(result)

    st.divider()

    # ==================== Skill 列表 ====================
    st.header("🧩 可用 Skill")

    try:
        from skill_support import get_skill_registry
        registry = get_skill_registry()
        skills = registry.list_all()
        if skills:
            # 按分类分组显示
            categories: dict[str, list] = {}
            for s in skills:
                categories.setdefault(s.category, []).append(s)

            for cat, cat_skills in sorted(categories.items()):
                cat_emoji = {"anime": "🎬", "utility": "🔧", "file": "📁", "life": "🌟"}.get(cat, "📋")
                with st.expander(f"{cat_emoji} {cat} ({len(cat_skills)})"):
                    for s in cat_skills:
                        status = "✅" if s.enabled else "⛔"
                        st.caption(
                            f"{status} {s.emoji} **{s.name}** "
                            f"(优先级:{s.priority})"
                        )
                        if s.description:
                            st.caption(f"　{s.description[:100]}…")
                        st.caption("---")
        else:
            st.caption("⚠️ 未加载到任何 Skill")
    except Exception as e:
        st.caption(f"⚠️ Skill 系统未就绪: {e}")

# ==================== 主界面 ====================

st.title("🤖 MutiRoleAgent")
st.caption("基于 ReAct Agent + bangumi/yuc 动漫数据 + 高德天气 MCP | 支持多轮对话 · 角色扮演")
st.divider()

def _format_display_time(time_str: str) -> str:
    """智能时间格式化：当天只显示 HH:MM，非当天显示完整日期。

    Args:
        time_str: 时间字符串，格式 "%Y-%m-%d %H:%M"

    Returns:
        格式化后的显示字符串。
    """
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        if dt.date() == date.today():
            return dt.strftime("%H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        # 兼容旧格式（仅 HH:MM）
        return time_str


# ---- 渲染历史消息 ----
for message in st.session_state["message"]:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message.get("time"):
            st.caption(f"🕐 {_format_display_time(message['time'])}")

# ---- 用户输入处理 ----
prompt = st.chat_input(
    placeholder="聊聊动漫、问问天气、或者让我给你推荐一部好番……"
)

if prompt:
    # 1) 展示用户消息
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with st.chat_message("user"):
        st.write(prompt)
        st.caption(f"🕐 {_format_display_time(now)}")
    st.session_state["message"].append({"role": "user", "content": prompt, "time": now})

    # 2) 流式获取 Agent 回复，按事件类型分流渲染
    response_chunks: list[str] = []
    status_placeholder = st.empty()
    text_placeholder = st.chat_message("assistant").empty()
    displayed_text = ""

    # 初始等待提示
    status_placeholder.info("⏳ 正在思考，请耐心等待…")

    try:
        for event in agent.execute_stream(prompt):
            if isinstance(event, TextChunk):
                # 首次收到文字时清除等待状态
                if not response_chunks:
                    status_placeholder.empty()
                response_chunks.append(event.content)
                for char in event.content:
                    displayed_text += char
                    text_placeholder.write(displayed_text + "▌")
                    time.sleep(0.01)
                text_placeholder.write(displayed_text)

            elif isinstance(event, ToolEvent):
                display_name = get_tool_display_name(event.tool_name)
                if event.phase == "start":
                    status_placeholder.warning(
                        f"⏳ 正在检索资料，请耐心等待…\n\n{display_name} — 执行中…"
                    )
                elif event.phase == "end":
                    status_placeholder.info(
                        f"⏳ 正在检索资料，请耐心等待…\n\n{display_name} — 已完成 ✓"
                    )

            # Phase 6: 结构化数据事件
            elif isinstance(event, StructuredData):
                if event.formatted:
                    displayed_text += f"\n\n---\n\n{event.formatted}"
                    text_placeholder.write(displayed_text)

        status_placeholder.empty()
        full_response = "".join(response_chunks)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        text_placeholder.write(full_response + f"\n\n🕐 {_format_display_time(now)}")
        st.session_state["message"].append({"role": "assistant", "content": full_response, "time": now})

    except Exception as e:
        logger.error(f"[app] 聊天处理异常: {type(e).__name__}: {e}", exc_info=True)
        status_placeholder.error(f"处理请求时出错: {str(e)[:100]}")
        st.rerun()
