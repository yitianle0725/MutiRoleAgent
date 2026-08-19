"""站点级配置快照路由。

把当前运行时的重要配置（模型、语音、存储等）聚合为一个只读快照，
供前端「设置面板」展示。**绝不返回任何 API Key 等敏感字段。**
"""

from __future__ import annotations

import os

from fastapi import APIRouter

from utils.config_handler import agent_config, rag_config
from utils.persona_loader import persona_loader

router = APIRouter(tags=["web"])


def _safe_env(name: str, default: str = "") -> str:
    return os.getenv(name) or default


@router.get("/config")
async def get_config():
    """返回当前配置快照（只读，非敏感）。"""
    return {
        "llm": {
            "model": rag_config.get("chat_model_name") or _safe_env("LLM_MODEL"),
            "base_url": _safe_env("LLM_BASE_URL"),
        },
        "embedding": {
            "mode": _safe_env("EMBEDDING_MODE", "auto"),
        },
        "voice": {
            "enabled": _safe_env("VOICE_ENABLED", "false").lower() == "true",
            "tts_model": _safe_env("ALI_TTS_MODEL"),
            "tts_voice": _safe_env("ALI_TTS_VOICE"),
            "asr_model": _safe_env("ALI_ASR_MODEL"),
        },
        "store": {
            "session": _safe_env("SESSION_STORE"),
            "db": _safe_env("DB_BACKEND"),
        },
        "agent": {
            # agent.yaml 顶层键里挑出一些常见配置项；缺失则返回空
            "max_steps": agent_config.get("max_steps")
            or agent_config.get("agent", {}).get("max_steps")
            or None,
            "personas": persona_loader.available_names,
        },
    }
