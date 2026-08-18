"""Silero-VAD 的本地离线封装。

模型以懒加载方式初始化。第一次使用需要本机已安装 ``silero-vad`` 及其
依赖；检测过程不上传用户音频。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


class VadUnavailableError(RuntimeError):
    """本地 VAD 依赖未安装或模型无法加载。"""


@dataclass(frozen=True)
class VadResult:
    """语音段检测结果。"""

    has_speech: bool
    speech_duration_ms: int


@lru_cache(maxsize=1)
def _load_model() -> tuple[Any, Any]:
    try:
        from silero_vad import get_speech_timestamps, load_silero_vad
    except ImportError as error:
        raise VadUnavailableError(
            "未安装 Silero-VAD。请执行 pip install -r requirements.txt。"
        ) from error

    try:
        return load_silero_vad(), get_speech_timestamps
    except Exception as error:
        raise VadUnavailableError(f"Silero-VAD 模型加载失败: {error}") from error


class SileroVadDetector:
    """检测 16 kHz 单声道 PCM 中是否存在有效语音。"""

    def detect_pcm16(self, pcm_data: bytes, sample_rate: int = 16000) -> VadResult:
        """同步检测 PCM 数据。

        调用方在异步上下文中应通过 ``asyncio.to_thread`` 调用本方法，避免
        推理占用事件循环。
        """
        if sample_rate not in {8000, 16000}:
            raise ValueError("Silero-VAD 仅支持 8000 或 16000 Hz 音频")
        if not pcm_data:
            return VadResult(has_speech=False, speech_duration_ms=0)

        try:
            import torch
        except ImportError as error:
            raise VadUnavailableError(
                "Silero-VAD 依赖 PyTorch，请按 silero-vad 的安装说明安装。"
            ) from error

        model, get_speech_timestamps = _load_model()
        samples = torch.frombuffer(bytearray(pcm_data), dtype=torch.int16).float() / 32768.0
        timestamps = get_speech_timestamps(samples, model, sampling_rate=sample_rate)
        speech_samples = sum(item["end"] - item["start"] for item in timestamps)
        duration_ms = int(speech_samples * 1000 / sample_rate)
        return VadResult(has_speech=duration_ms > 0, speech_duration_ms=duration_ms)
