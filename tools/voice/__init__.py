"""语音交互能力。

语音模块位于渠道/UI 与 Agent 核心之间：它把音频转成文本，或把最终
回复文本转成音频；不参与 Agent 的工具决策和业务逻辑。
"""

from tools.voice.voice_state import VoiceState, VoiceStateMachine

__all__ = ["VoiceState", "VoiceStateMachine"]
