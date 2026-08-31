"""聊天流式路由。

把统一 HarnessEvent 直接作为 SSE 事件推送。

复用 ``channels.manager.agent_cache`` —— 与 Streamlit / CLI 共享同一个
已初始化的 Agent 实例，避免重复加载 MCP 工具与 RAG 知识库。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from channels.platforms.fastapi import conversation_coordinator, harness_event_sse_message

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """一次聊天请求的入参。"""

    query: str = Field(..., description="用户输入的文本")
    session_id: str | None = Field(default=None, description="会话唯一标识，缺省用 default")


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest) -> EventSourceResponse:
    """SSE 流式聊天：Agent 产出一行，前端实时推送一行。"""
    async def event_generator():
        try:
            async for event in conversation_coordinator.handle_user_turn_stream(
                req.query,
                session_id=req.session_id or "default",
            ):
                yield harness_event_sse_message(event)
        except Exception as exc:
            # 正常执行异常已由 Coordinator 转成 run_end；这里只处理传输层异常。
            from agent.harness_events import HarnessEvent

            yield harness_event_sse_message(HarnessEvent(
                type="run_end",
                data={"status": "failed", "error": str(exc)},
            ))

    return EventSourceResponse(event_generator())


@router.get("/chat/health")
async def chat_health() -> dict[str, str]:
    """轻量健康检查（避免实际初始化 Agent，仅探活）。"""
    return {
        "name": "MutiRoleAgent API",
        "status": "ok",
    }
