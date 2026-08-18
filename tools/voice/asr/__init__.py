"""语音识别适配器。"""

from tools.voice.asr.ali_qwen_asr import AliRealtimeAsr
from tools.voice.asr.base_asr import AsrError, AsrResult, BaseAsr

__all__ = ["AliRealtimeAsr", "AsrError", "AsrResult", "BaseAsr"]
