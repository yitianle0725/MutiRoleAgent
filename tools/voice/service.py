"""语音服务组合、WAV 解码和 Streamlit 同步调用辅助函数。"""

from __future__ import annotations

import asyncio
import io
import os
import wave
from dataclasses import dataclass

from tools.voice.asr import AliRealtimeAsr, AsrResult
from tools.voice.tts import AliStreamTts, TtsResult
from tools.voice.vad_detector import SileroVadDetector, VadResult
from utils.logger_handler import logger


class VoiceInputError(ValueError):
    """浏览器录音无法用于当前语音服务。"""


@dataclass(frozen=True)
class PcmAudio:
    """标准化后的 16-bit PCM 音频。"""

    data: bytes
    sample_rate: int


def decode_wav_to_pcm16(wav_data: bytes) -> PcmAudio:
    """读取单声道 16-bit WAV；明确拒绝未实现的格式转换。"""
    try:
        with wave.open(io.BytesIO(wav_data), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            compression_type = reader.getcomptype()
            frames = reader.readframes(reader.getnframes())
    except wave.Error as error:
        raise VoiceInputError("录音必须是 WAV 格式。") from error

    if compression_type != "NONE":
        raise VoiceInputError("录音必须是未压缩的 PCM WAV 格式。")
    if channels != 1 or sample_width != 2 or sample_rate != 16000:
        raise VoiceInputError(
            "当前语音 MVP 仅接受 16 kHz、单声道、16-bit WAV 录音。"
        )
    return PcmAudio(data=frames, sample_rate=sample_rate)


class VoiceConversationService:
    """把 VAD、ASR、TTS 组合为 UI 可调用的语音服务。"""

    def __init__(self) -> None:
        self._vad = SileroVadDetector()
        self._asr = AliRealtimeAsr()
        self._tts = AliStreamTts()

    @property
    def configured(self) -> bool:
        return os.getenv("VOICE_ENABLED", "false").lower() == "true" and bool(
            os.getenv("DASHSCOPE_API_KEY")
        )

    async def transcribe_wav(self, wav_data: bytes) -> tuple[AsrResult, VadResult]:
        """本地 VAD 检测通过后，再上传 PCM 到阿里云转写。"""
        pcm = decode_wav_to_pcm16(wav_data)
        logger.info(
            "[voice] ASR input: wav_bytes=%d pcm_bytes=%d sample_rate=%d",
            len(wav_data),
            len(pcm.data),
            pcm.sample_rate,
        )
        vad_result = await asyncio.to_thread(
            self._vad.detect_pcm16, pcm.data, pcm.sample_rate
        )
        if not vad_result.has_speech:
            raise VoiceInputError("未检测到有效语音，请录音后重试。")
        logger.info(
            "[voice] VAD passed: speech_duration_ms=%d",
            vad_result.speech_duration_ms,
        )
        result = await self._asr.transcribe_pcm(pcm.data, pcm.sample_rate)
        return result, vad_result

    async def synthesize_reply(self, text: str) -> TtsResult:
        """把 Agent 最终文本交给 TTS。"""
        return await self._tts.synthesize(text)


voice_conversation_service = VoiceConversationService()
