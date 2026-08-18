"""Qwen Audio 3.0 Realtime WebSocket 适配器。

该模块不负责录音或播放，只封装官方 Quickstart 中的事件协议，方便 UI 层
按需接入。音频必须是 16 kHz、单声道、16-bit PCM，发送时使用 Base64。
"""

from __future__ import annotations

import base64
import json
import os


class QwenRealtimeClient:
    model = "qwen-audio-3.0-realtime-plus"

    def __init__(self, api_key: str | None = None, websocket_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.model = os.getenv("ALI_REALTIME_MODEL", self.model)
        workspace = os.getenv("DASHSCOPE_WORKSPACE_ID", "")
        default_url = (
            f"wss://{workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model={self.model}"
            if workspace else
            f"wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={self.model}"
        )
        self.websocket_url = websocket_url or os.getenv("ALI_REALTIME_WS_URL", default_url)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def session_update(self, voice: str | None = None) -> str:
        return json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": voice or os.getenv("ALI_TTS_VOICE", "longanqian"),
                "turn_detection": {"type": "server_vad", "threshold": 0.5, "silence_duration_ms": 800},
            },
        })

    @staticmethod
    def append_audio(pcm_chunk: bytes) -> str:
        if not pcm_chunk:
            raise ValueError("音频帧不能为空")
        return json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm_chunk).decode("ascii")})

    @staticmethod
    def decode_audio_delta(event: dict) -> bytes:
        encoded = event.get("delta", "")
        return base64.b64decode(encoded) if encoded else b""
