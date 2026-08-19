"""语音合成（TTS）与识别（ASR）路由。

统一走 ``tools.voice.service.voice_conversation_service`` —— 与 CLI 复用同一
语音服务组合（VAD + ASR + TTS），本模块只做 HTTP 胶水，不重写任何识别/合成逻辑。
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from tools.voice.service import VoiceInputError, voice_conversation_service

router = APIRouter(tags=["voice"])


class TtsRequest(BaseModel):
    """TTS 合成入参。"""

    text: str = Field(..., description="要合成语音的文本")


def _require_voice_enabled() -> None:
    """语音服务未就绪时统一抛出 503。"""
    if not voice_conversation_service.configured:
        raise HTTPException(
            status_code=503,
            detail="语音服务不可用：请确认已安装 dashscope、设置 VOICE_ENABLED=true 与 DASHSCOPE_API_KEY",
        )


@router.post("/voice/tts")
async def synthesize_tts(req: TtsRequest):
    """把文本合成为语音音频，直接返回二进制（配合前端 Audio 播放）。"""
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="语音合成文本不能为空")

    _require_voice_enabled()

    try:
        result = await voice_conversation_service.synthesize_reply(text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"语音合成失败: {exc}") from exc

    from fastapi.responses import Response

    return Response(
        content=result.audio_data,
        media_type=result.mime_type,  # 前端据此选择解码方式
        headers={"X-TTS-Provider": result.provider},
    )


@router.post("/voice/asr")
async def transcribe_audio(file: UploadFile = File(...)):
    """把一段 16kHz 单声道 16bit WAV 录音转写成文字。

    复用 ``voice_conversation_service.transcribe_wav``（内部已组合本地 VAD 检测
    + 阿里云 ASR）。前端录音需按 16kHz/单声道/16bit 导出，否则 decode 会直接 400。
    """
    _require_voice_enabled()

    wav_bytes = await file.read()
    try:
        result, vad = await voice_conversation_service.transcribe_wav(wav_bytes)
    except VoiceInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"语音识别失败: {exc}") from exc

    return {
        "text": result.text,
        "is_final": result.is_final,
        "provider": result.provider,
        "speech_ms": vad.speech_duration_ms,
    }
