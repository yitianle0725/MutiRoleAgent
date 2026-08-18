"""DashScope Qwen Audio 3.0 TTS 适配器。"""

from __future__ import annotations

import asyncio
import os
from tools.voice.tts.base_tts import BaseTts, TtsError, TtsResult
from utils.logger_handler import logger


class AliStreamTts(BaseTts):
    provider_name = "aliyun_qwen_audio_tts"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 voice: str | None = None, workspace: str | None = None,
                 timeout_seconds: float = 45.0) -> None:
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self._model = model or os.getenv("ALI_TTS_MODEL", "qwen-audio-3.0-tts-plus")
        self._voice = voice or os.getenv("ALI_TTS_VOICE", "longanhuan_v3.6")
        self._workspace = workspace or os.getenv("DASHSCOPE_WORKSPACE_ID")
        self._timeout_seconds = timeout_seconds
        logger.info("[voice] TTS initialized: model=%s voice=%s", self._model, self._voice)

    async def synthesize(self, text: str) -> TtsResult:
        clean_text = text.strip()
        if not clean_text:
            raise TtsError("没有可朗读的文本。")
        if not self._api_key:
            raise TtsError("未配置 DASHSCOPE_API_KEY，无法使用阿里云语音合成。")
        try:
            audio = await asyncio.wait_for(asyncio.to_thread(self._synthesize_sync, clean_text), self._timeout_seconds)
        except asyncio.TimeoutError as error:
            raise TtsError("语音合成超时，请稍后重试。") from error
        except TtsError:
            raise
        except Exception as error:
            raise TtsError(f"阿里云语音合成失败: {error}") from error
        if not audio:
            raise TtsError("语音合成未返回音频数据。")
        return TtsResult(audio_data=audio, mime_type="audio/mpeg", provider=self.provider_name)

    def _synthesize_sync(self, text: str) -> bytes:
        try:
            import dashscope
            from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer
        except ImportError as error:
            raise TtsError("未安装 dashscope，请执行 pip install dashscope。") from error
        dashscope.api_key = self._api_key
        workspace_url = os.getenv("ALI_DASHSCOPE_WS_URL")
        if workspace_url:
            dashscope.base_websocket_api_url = workspace_url
        elif self._workspace:
            dashscope.base_websocket_api_url = (
                f"wss://{self._workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
            )
        synthesizer = SpeechSynthesizer(
            model=self._model,
            voice=self._voice,
            format=AudioFormat.MP3_24000HZ_MONO_256KBPS,
            workspace=self._workspace,
        )
        audio = synthesizer.call(text)
        if isinstance(audio, bytearray):
            return bytes(audio)
        if isinstance(audio, bytes):
            return audio
        raise TtsError(f"TTS 返回了不支持的音频类型: {type(audio).__name__}")

    # 保留旧协议构造方法，便于已有单测和排查工具使用。
    def _build_start_message(self, task_id: str) -> dict:
        return {"header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"task_group": "audio", "task": "tts", "function": "speech_synthesizer", "model": self._model, "input": {}, "parameters": {"text_type": "PlainText", "voice": self._voice, "format": "mp3", "sample_rate": 24000}}}

    @staticmethod
    def _build_text_message(task_id: str, text: str) -> dict:
        return {"header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {"text": text}}}

    @staticmethod
    def _build_finish_message(task_id: str) -> dict:
        return {"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}}
