"""
FastAPI Channel
===============
提供 REST + SSE + WebSocket 三种协议接入 Agent，参考 EchoBot ``channels/platforms/`` 的
adapter 模式封装。

启动方式::

    # 方式 1：直接 uvicorn
    uvicorn channels.platforms.fastapi:app --reload --port 8000

    # 方式 2：通过 Channel
    python -c "import asyncio; from channels.platforms.fastapi import channel; asyncio.run(channel.start())"

端点一览
--------
======== ====================================== ==========
方法      路径                                   说明
======== ====================================== ==========
POST     /api/v1/chat/stream                    SSE 流式聊天
WS       /api/v1/ws/{session_id}                WebSocket 双向流
GET      /api/v1/sessions                       会话列表
POST     /api/v1/sessions                       新建会话
GET      /api/v1/sessions/{session_id}          会话详情 + 消息
DELETE   /api/v1/sessions/{session_id}          清空会话
GET      /health                                健康检查
======== ====================================== ==========

SSE 事件格式::

    event: text
    data: {"content": "你好"}

    event: tool_start
    data: {"tool_name": "search_anime", "tool_args": {...}}

    event: tool_end
    data: {"tool_name": "search_anime", "result_preview": "..."}

    event: structured_data
    data: {"schema_type": "anime", "model": "...", "formatted": "..."}

    event: done
    data: {}
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.react_agent import ReactAgent
from agent.stream_events import TextChunk, ToolEvent, StructuredData, get_tool_display_name
from channels.base import Channel
from channels.manager import agent_cache
from memory.chat_db import chat_db
from observability.store import monitor_store
from utils.logger_handler import logger

# ==================== Pydantic 模型 ====================


class ChatRequest(BaseModel):
    """SSE 流式聊天请求体。"""

    message: str = Field(..., description="用户输入文本", min_length=1)
    session_id: str = Field(default="default", description="会话唯一标识")
    user_id: str | None = Field(default=None, description="用户 ID（可选）")
    persona: str | None = Field(default=None, description="角色人设（可选，如 'Cyrene'）")


class SessionInfo(BaseModel):
    """会话列表项。"""

    session_id: str
    title: str = ""
    user_id: str = ""
    message_count: int = 0
    updated_at: str | None = None


class SessionDetail(BaseModel):
    """会话详情（含消息历史）。"""

    session_id: str
    title: str = ""
    user_id: str = ""
    message_count: int = 0
    messages: list[dict] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class CreateSessionRequest(BaseModel):
    """新建会话请求体。"""

    session_id: str | None = Field(default=None, description="自定义会话 ID，不传则自动生成")
    title: str | None = Field(default=None, description="会话标题")
    user_id: str | None = Field(default=None, description="用户 ID")


class HealthResponse(BaseModel):
    status: str = "ok"
    channel: str = "fastapi"
    agent_cache_size: int = 0


# ==================== Agent 初始化辅助 ====================

# 每个 session_id 一把异步锁，防止并发请求重复初始化 Agent
_init_locks: dict[str, asyncio.Lock] = {}
_init_locks_lock = asyncio.Lock()


async def _get_or_create_agent(
    session_id: str,
    user_id: str | None = None,
    persona: str | None = None,
) -> ReactAgent:
    """从缓存获取 Agent，缓存未命中则初始化并放入缓存。

    同一 session_id 的并发请求只初始化一次（asyncio.Lock 保护）。
    """
    # 快速路径：缓存命中
    agent = agent_cache.get(session_id)
    if agent is not None:
        # 如果 user_id 或 persona 变化了，重建 agent
        if (user_id and agent.user_id != user_id) or (persona and agent.default_persona != persona):
            agent_cache.evict(session_id)
        else:
            return agent

    # 获取或创建该 session 的初始化锁
    async with _init_locks_lock:
        if session_id not in _init_locks:
            _init_locks[session_id] = asyncio.Lock()

    async with _init_locks[session_id]:
        # 双重检查：等锁期间可能已被其它请求初始化
        agent = agent_cache.get(session_id)
        if agent is not None:
            return agent

        logger.info(
            f"[FastAPI] 初始化 Agent: session={session_id[:12]}…, "
            f"user={user_id}, persona={persona}"
        )
        agent = ReactAgent(
            session_id=session_id,
            user_id=user_id,
            default_persona=persona,
        )
        await agent.init_agent()
        agent_cache.put(session_id, agent)
        return agent


# ==================== FastAPI 应用 ====================


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """FastAPI 生命周期：启动/关闭时管理 Agent 缓存。"""
    logger.info("[FastAPI] Channel 启动中…")
    # 预初始化默认 Agent
    try:
        await _get_or_create_agent("default")
        logger.info("[FastAPI] 默认 Agent 预初始化完成")
    except Exception as e:
        logger.warning(f"[FastAPI] 默认 Agent 预初始化失败（不影响使用）: {e}")
    yield
    # 关闭
    logger.info("[FastAPI] Channel 关闭中…")
    agent_cache.clear()
    await asyncio.to_thread(monitor_store.close)


def _create_app() -> FastAPI:
    """创建 FastAPI 应用（CORS + lifespan + 路由注册）。"""
    app = FastAPI(
        title="MutiRoleAgent API",
        description="REST + SSE + WebSocket 聊天 API",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # CORS：本地开发全开
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 健康检查 ----

    @app.get("/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(agent_cache_size=agent_cache.size)

    # ---- 运行监控 ----

    @app.get("/api/v1/monitor/summary")
    async def monitor_summary():
        """获取最近运行的成功率、延迟和 token 汇总。"""
        return await asyncio.to_thread(monitor_store.summary)

    @app.get("/api/v1/monitor/turns")
    async def monitor_turns(limit: int = 50):
        """获取最近的 Agent 执行轮次摘要。"""
        return await asyncio.to_thread(monitor_store.list_turns, limit)

    @app.get("/api/v1/monitor/traces/{trace_id}")
    async def monitor_trace(trace_id: str):
        """获取单次执行的结构化追踪事件。"""
        trace = await asyncio.to_thread(monitor_store.get_trace, trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return trace

    # ---- SSE 流式聊天 ----

    @app.post("/api/v1/chat/stream")
    async def chat_stream(req: ChatRequest):
        """SSE 流式聊天。

        遍历 Agent 的异步流式输出，将 ``TextChunk`` / ``ToolEvent`` / ``StructuredData``
        格式化为 SSE 事件流，浏览器原生 ``EventSource`` 可直接消费。
        """
        agent = await _get_or_create_agent(
            session_id=req.session_id,
            user_id=req.user_id,
            persona=req.persona,
        )

        async def event_stream() -> AsyncIterator[str]:
            try:
                async for event in agent.execute_stream_async(req.message):
                    if isinstance(event, TextChunk):
                        yield _sse_event("text", {"content": event.content})

                    elif isinstance(event, ToolEvent):
                        if event.phase == "start":
                            yield _sse_event("tool_start", {
                                "tool_name": event.tool_name,
                                "tool_args": event.tool_args or {},
                            })
                        elif event.phase == "end":
                            yield _sse_event("tool_end", {
                                "tool_name": event.tool_name,
                                "result_preview": event.result_preview or "",
                            })

                    elif isinstance(event, StructuredData):
                        yield _sse_event("structured_data", {
                            "schema_type": event.schema_type,
                            "model": event.model,
                            "formatted": event.formatted,
                        })

                yield _sse_event("done", {})
            except Exception as e:
                logger.error(f"[FastAPI SSE] 流式异常: {type(e).__name__}: {e}", exc_info=True)
                yield _sse_event("error", {"message": str(e)[:200]})

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ---- WebSocket ----

    @app.websocket("/api/v1/ws/{session_id}")
    async def ws_chat(ws: WebSocket, session_id: str):
        """WebSocket 双向流式聊天。

        客户端帧::

            {"type": "chat", "message": "你好", "persona": "Cyrene", "user_id": "1001"}

        服务端帧::

            {"event": "text", "data": {"content": "你"}}
            {"event": "tool_start", "data": {"tool_name": "...", "tool_args": {...}}}
            {"event": "tool_end", "data": {"tool_name": "...", "result_preview": "..."}}
            {"event": "done"}
        """
        await ws.accept()
        logger.info(f"[FastAPI WS] 连接: session={session_id[:12]}…")

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.send_json({"event": "error", "data": {"message": "无效 JSON"}})
                    continue

                msg_type = data.get("type", "")
                if msg_type != "chat":
                    await ws.send_json({"event": "error", "data": {"message": f"未知 type: {msg_type}"}})
                    continue

                message = data.get("message", "").strip()
                if not message:
                    continue

                persona = data.get("persona")
                user_id = data.get("user_id")

                agent = await _get_or_create_agent(
                    session_id=session_id,
                    user_id=user_id,
                    persona=persona,
                )

                async for event in agent.execute_stream_async(message):
                    if isinstance(event, TextChunk):
                        await ws.send_json({"event": "text", "data": {"content": event.content}})

                    elif isinstance(event, ToolEvent):
                        if event.phase == "start":
                            await ws.send_json({"event": "tool_start", "data": {
                                "tool_name": event.tool_name,
                                "tool_args": event.tool_args or {},
                            }})
                        elif event.phase == "end":
                            await ws.send_json({"event": "tool_end", "data": {
                                "tool_name": event.tool_name,
                                "result_preview": event.result_preview or "",
                            }})

                    elif isinstance(event, StructuredData):
                        await ws.send_json({"event": "structured_data", "data": {
                            "schema_type": event.schema_type,
                            "model": event.model,
                            "formatted": event.formatted,
                        }})

                await ws.send_json({"event": "done"})

        except WebSocketDisconnect:
            logger.info(f"[FastAPI WS] 断开: session={session_id[:12]}…")
        except Exception as e:
            logger.error(f"[FastAPI WS] 异常: {type(e).__name__}: {e}", exc_info=True)

    # ---- 会话管理 REST API ----

    @app.get("/api/v1/sessions", response_model=list[SessionInfo])
    async def list_sessions(limit: int = 20):
        """获取会话列表（含标题、消息数）。"""
        rows = chat_db.list_sessions_with_meta(limit=limit)
        return [
            SessionInfo(
                session_id=r["session_id"],
                title=r.get("title", ""),
                user_id=r.get("user_id", ""),
                message_count=r.get("message_count", 0),
                updated_at=r.get("updated_at"),
            )
            for r in rows
        ]

    @app.post("/api/v1/sessions", response_model=SessionInfo)
    async def create_session(req: CreateSessionRequest):
        """创建新会话。"""
        sid = req.session_id or str(uuid.uuid4())
        chat_db.upsert_session_meta(
            session_id=sid,
            title=req.title or "",
            user_id=req.user_id or "",
            message_count=0,
        )
        logger.info(f"[FastAPI] 创建会话: {sid[:12]}…")
        return SessionInfo(session_id=sid, title=req.title or "", user_id=req.user_id or "")

    @app.get("/api/v1/sessions/{session_id}", response_model=SessionDetail)
    async def get_session(session_id: str):
        """获取会话详情（含消息历史、元数据）。"""
        meta = chat_db.get_session_meta(session_id)
        messages = chat_db.get_history_raw(session_id)
        return SessionDetail(
            session_id=session_id,
            title=meta["title"] if meta else "",
            user_id=meta["user_id"] if meta else "",
            message_count=len(messages),
            messages=messages,
            created_at=meta.get("created_at") if meta else None,
            updated_at=meta.get("updated_at") if meta else None,
        )

    @app.delete("/api/v1/sessions/{session_id}")
    async def delete_session(session_id: str):
        """清空会话（DB + 内存 + Agent 缓存）。"""
        chat_db.clear_session(session_id)
        agent_cache.evict(session_id)
        # 清理 session_store
        try:
            from memory.session_store import session_store
            session_store.clear(session_id)
        except Exception:
            pass
        logger.info(f"[FastAPI] 删除会话: {session_id[:12]}…")
        return {"status": "deleted", "session_id": session_id}

    return app


# ==================== SSE 辅助 ====================


def _sse_event(event: str, data: dict) -> str:
    """格式化一条 SSE 事件。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


# ==================== Channel 封装 ====================


class FastAPIChannel(Channel):
    """FastAPI channel：通过 uvicorn 启动 FastAPI 应用。

    使用方式::

        import asyncio
        from channels.platforms.fastapi import channel
        asyncio.run(channel.start())
    """

    name = "fastapi"

    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        super().__init__()
        self._host = host
        self._port = port
        self._server: uvicorn.Server | None = None
        self._app = _create_app()

    @property
    def app(self) -> FastAPI:
        """暴露 FastAPI 应用实例（供 uvicorn 命令行使用）。"""
        return self._app

    async def start(self) -> None:
        """启动 uvicorn 服务器（阻塞当前 asyncio 任务）。"""
        self._running = True
        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        logger.info(f"[FastAPI] 启动 http://{self._host}:{self._port}")
        await self._server.serve()

    async def stop(self) -> None:
        """优雅关闭 uvicorn 服务器。"""
        self._running = False
        if self._server is not None:
            self._server.should_exit = True
            logger.info("[FastAPI] 关闭中…")


# ==================== 模块级实例 ====================

# 供 ``uvicorn channels.platforms.fastapi:app`` 使用
channel = FastAPIChannel()
app = channel.app
