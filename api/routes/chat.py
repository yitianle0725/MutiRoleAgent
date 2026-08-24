"""聊天流式路由。

把 Agent 的异步事件流（``TextChunk`` / ``ToolEvent`` / ``StructuredData``）
翻译成 SSE 事件推送，供前端 React 界面消费。

复用 ``channels.manager.agent_cache`` —— 与 Streamlit / CLI 共享同一个
已初始化的 Agent 实例，避免重复加载 MCP 工具与 RAG 知识库。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from agent.react_agent import ReactAgent
from agent.stream_events import StructuredData, TextChunk, ToolEvent
from channels.manager import agent_cache
from orchestration.coordinator import ConversationCoordinator
from orchestration.session_runner import SessionAgentRunner

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """一次聊天请求的入参。"""

    query: str = Field(..., description="用户输入的文本")
    session_id: str | None = Field(default=None, description="会话唯一标识，缺省用 default")
    user_id: str | None = Field(default=None, description="用户 ID，可选")
    persona: str | None = Field(default=None, description="角色人设名，如 Cyrene")


async def get_or_create_agent(req: ChatRequest) -> ReactAgent:
    """异步地获取（或创建并初始化）一个就绪 Agent。

    逻辑对齐 ``app.py::_init_agent_sync``，但这里是纯 async 版本：
    缓存未命中时直接 ``await agent.init_agent()``，无需后台线程包装。
    """
    session_id = req.session_id or "default"
    cached = agent_cache.get(session_id)

    if cached is not None:
        # 角色 / 用户变化时淘汰旧缓存，重建
        changed = (req.user_id and cached.user_id != req.user_id) or (
            req.persona and cached.default_persona != req.persona
        )
        if changed:
            agent_cache.evict(session_id)
        else:
            return cached

    agent = ReactAgent(
        session_id=session_id,
        user_id=req.user_id,
        default_persona=req.persona,
    )
    try:
        await agent.init_agent()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Agent 初始化失败: {exc}") from exc
    agent_cache.put(session_id, agent)
    return agent


async def _agent_factory(session_id: str, user_id: str | None, persona: str | None) -> ReactAgent:
    return await get_or_create_agent(
        ChatRequest(query="", session_id=session_id, user_id=user_id, persona=persona)
    )


conversation_coordinator = ConversationCoordinator(SessionAgentRunner(_agent_factory))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    """SSE 流式聊天：Agent 产出一行，前端实时推送一行。"""
    async def event_generator():
        try:
            async for event in conversation_coordinator.handle_user_turn_stream(
                req.query,
                session_id=req.session_id or "default",
                user_id=req.user_id,
                persona=req.persona,
            ):
                if isinstance(event, TextChunk):
                    # 逐段文字，前端做打字机效果
                    yield {"event": "chunk", "data": event.content}
                elif isinstance(event, ToolEvent):
                    # data 必须是 JSON 字符串（sse-starlette 对 dict 会 str() 成
                    # Python repr，前端 JSON.parse 会失败），这里手动序列化。
                    yield {
                        "event": "tool",
                        "data": json.dumps(
                            {
                                "phase": event.phase,
                                "tool_name": event.tool_name,
                                "tool_args": event.tool_args,
                                "result_preview": event.result_preview,
                            },
                            ensure_ascii=False,
                        ),
                    }
                elif isinstance(event, StructuredData):
                    # 结构化输出（番剧卡 / 天气卡 等）：把 schema_type、raw_json、formatted
                    # 一起 JSON 序列化下发，前端按 schema_type 渲染对应卡片（避免展示原始 JSON）
                    yield {
                        "event": "structured",
                        "data": json.dumps(
                            {
                                "schema_type": event.schema_type,
                                "raw_json": event.raw_json,
                                "formatted": event.formatted,
                            },
                            ensure_ascii=False,
                        ),
                    }
            yield {"event": "done", "data": ""}
        except Exception as exc:
            # Agent 出错时也发事件而非断开连接，前端能展示给用户
            yield {"event": "error", "data": str(exc)}

    return EventSourceResponse(event_generator())


@router.get("/chat/health")
async def chat_health() -> dict[str, str]:
    """轻量健康检查（避免实际初始化 Agent，仅探活）。"""
    return {
        "name": "MutiRoleAgent API",
        "status": "ok",
    }
