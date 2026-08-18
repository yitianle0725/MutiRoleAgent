"""ASR 供应商无关接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class AsrError(RuntimeError):
    """语音识别错误，可安全展示给 UI。"""


@dataclass(frozen=True)
class AsrResult:
    """标准化转写结果。"""

    text: str
    is_final: bool
    provider: str


class BaseAsr(ABC):
    """把 16-bit PCM 流转写为文本的抽象基类。"""

    @abstractmethod
    async def transcribe_pcm(
        self,
        pcm_data: bytes,
        sample_rate: int = 16000,
    ) -> AsrResult:
        """转写一段单声道 PCM 音频。"""
        raise NotImplementedError
