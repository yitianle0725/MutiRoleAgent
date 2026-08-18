"""DashScope Qwen Audio 3.0 流式 ASR 适配器。

官方 SDK 负责 WebSocket 握手和协议细节，本模块只负责把 PCM 和结果转换成
项目统一的 BaseAsr 接口。
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from uuid import uuid4

from tools.voice.asr.base_asr import AsrError, AsrResult, BaseAsr


class AliRealtimeAsr(BaseAsr):
    provider_name = "aliyun_qwen_audio_asr"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 workspace: str | None = None, chunk_size: int = 3200,
                 timeout_seconds: float = 45.0) -> None:
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self._model = model or os.getenv("ALI_ASR_MODEL", "qwen-audio-3.0-asr-flash-streaming")
        self._workspace = workspace or os.getenv("DASHSCOPE_WORKSPACE_ID")
        self._chunk_size = chunk_size
        self._timeout_seconds = timeout_seconds

    async def transcribe_pcm(self, pcm_data: bytes, sample_rate: int = 16000) -> AsrResult:
        if not pcm_data:
            raise AsrError("没有可识别的音频数据。")
        if sample_rate != 16000:
            raise AsrError("Qwen Audio ASR 适配器仅接受 16000 Hz PCM。")
        if not self._api_key:
            raise AsrError("未配置 DASHSCOPE_API_KEY，无法使用阿里云语音识别。")
        try:
            return await asyncio.wait_for(asyncio.to_thread(self._transcribe_sync, pcm_data, sample_rate), self._timeout_seconds)
        except asyncio.TimeoutError as error:
            raise AsrError("语音识别超时，请缩短录音后重试。") from error
        except AsrError:
            raise
        except Exception as error:
            raise AsrError(f"阿里云语音识别失败: {error}") from error

    def _transcribe_sync(self, pcm_data: bytes, sample_rate: int) -> AsrResult:
        try:
            import dashscope
            from dashscope.audio.asr import Recognition, RecognitionCallback
        except ImportError as error:
            raise AsrError("未安装 dashscope，请执行 pip install dashscope。") from error

        dashscope.api_key = self._api_key
        workspace_url = os.getenv("ALI_DASHSCOPE_WS_URL")
        if workspace_url:
            dashscope.base_websocket_api_url = workspace_url
        elif self._workspace:
            dashscope.base_websocket_api_url = (
                f"wss://{self._workspace}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference"
            )
        result_text = [""]
        opened = threading.Event()
        completed = threading.Event()
        callback_error: list[str] = []

        class Callback(RecognitionCallback):
            def on_open(self) -> None:
                opened.set()

            def on_close(self) -> None:
                completed.set()

            def on_complete(self) -> None:
                completed.set()

            def on_error(self, message) -> None:
                callback_error.append(getattr(message, "message", str(message)))
                completed.set()

            def on_event(self, result) -> None:
                sentence = result.get_sentence() or {}
                text = sentence.get("text")
                if text:
                    result_text[0] = str(text)

        recognition = Recognition(
            model=self._model,
            format="pcm",
            sample_rate=sample_rate,
            workspace=self._workspace,
            semantic_punctuation_enabled=False,
            callback=Callback(),
        )
        recognition.start()
        if not opened.wait(8):
            recognition.stop()
            raise AsrError("阿里云 ASR WebSocket 建立失败，请检查 Workspace ID 和 API Key。")
        for index in range(0, len(pcm_data), self._chunk_size):
            recognition.send_audio_frame(pcm_data[index:index + self._chunk_size])
        recognition.stop()
        completed.wait(8)
        if callback_error:
            raise AsrError(callback_error[-1])
        text = result_text[0].strip()
        if not text:
            raise AsrError("未识别到有效语音，请靠近麦克风后重试。")
        return AsrResult(text=text, is_final=True, provider=self.provider_name)

    async def transcribe_stream(self, chunks: AsyncIterator[bytes] | list[bytes], sample_rate: int = 16000) -> AsyncIterator[AsrResult]:
        data = bytearray()
        if hasattr(chunks, "__aiter__"):
            async for chunk in chunks:  # type: ignore[union-attr]
                data.extend(chunk)
        else:
            for chunk in chunks:
                data.extend(chunk)
        yield await self.transcribe_pcm(bytes(data), sample_rate)

    # 保留旧协议构造方法，便于已有单测和排查工具使用。
    def _build_start_message(self, task_id: str, sample_rate: int) -> dict:
        return {"header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"task_group": "audio", "task": "asr", "function": "recognition", "model": self._model, "input": {}, "parameters": {"format": "pcm", "sample_rate": sample_rate}}}

    @staticmethod
    def _build_finish_message(task_id: str) -> dict:
        return {"header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"}, "payload": {"input": {}}}
