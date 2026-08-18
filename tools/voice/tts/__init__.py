"""语音合成适配器。"""

from tools.voice.tts.ali_qwen_tts import AliStreamTts
from tools.voice.tts.base_tts import BaseTts, TtsError, TtsResult

__all__ = ["AliStreamTts", "BaseTts", "TtsError", "TtsResult"]
