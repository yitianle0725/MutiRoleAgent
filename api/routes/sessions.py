"""会话管理路由。

复用 ``memory.chat_db`` 的持久化接口，本模块只做 HTTP 胶水。
所有数据库操作为同步 I/O，用 ``asyncio.to_thread`` 避免阻塞事件循环
（遵循项目 AGENTS.md 的异步原则）。
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException

from memory.chat_db import chat_db

router = APIRouter(tags=["sessions"])


@router.get("/sessions")
async def list_sessions(limit: int = 30):
    """返回最近的会话列表（按更新时间倒序）。"""
    sessions = await asyncio.to_thread(chat_db.list_sessions_with_meta, limit)
    return {"sessions": sessions}


@router.post("/sessions")
async def create_session():
    """新建一个空会话，返回新的 session_id。"""
    session_id = str(uuid.uuid4())
    await asyncio.to_thread(chat_db.upsert_session_meta, session_id, title="新会话", user_id="")
    return {"session_id": session_id}


@router.get("/sessions/{session_id}/history")
async def session_history(session_id: str, limit: int = 200):
    """返回指定会话的历史消息（原始 dict 格式，供前端回填）。"""
    history = await asyncio.to_thread(chat_db.get_history_raw, session_id, limit)
    return {"session_id": session_id, "history": history}


@router.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    """清空指定会话的全部记录。"""
    await asyncio.to_thread(chat_db.clear_session, session_id)
    return {"ok": True, "session_id": session_id}
