"""角色人设路由。

复用 ``utils.persona_loader`` —— 角色名列表与角色灵魂文本。
本模块只做 HTTP 胶水，不重写角色加载逻辑。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from utils.persona_loader import load_persona_overlay, persona_loader

router = APIRouter(tags=["persona"])


@router.get("/personas")
async def list_personas():
    """返回所有可用角色名。"""
    return {"names": persona_loader.available_names}


@router.get("/personas/{name}")
async def get_persona(name: str):
    """返回指定角色的灵魂文本（卡片内容）。"""
    soul = load_persona_overlay(name)
    if not soul:
        raise HTTPException(status_code=404, detail=f"角色不存在: {name}")
    return {"name": name, "overlay": soul}
