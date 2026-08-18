"""TTS 供应商无关接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class TtsError(RuntimeError):
    """语音合成错误，可安全展示给 UI。"""


@dataclass(frozen=True)
class TtsResult:
    """标准化语音合成结果。"""

    audio_data: bytes
    mime_type: str
    provider: str


class BaseTts(ABC):
    """把文本合成为可播放音频的抽象基类。"""

    @abstractmethod
    async def synthesize(self, text: str) -> TtsResult:
        """合成文本并返回音频字节。"""
        raise NotImplementedError
