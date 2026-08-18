"""语音对话状态机。

状态转换集中在这里，避免 Streamlit 重跑时把录音、思考和播放状态混在
多个 session_state 字段中。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VoiceState(StrEnum):
    """一次语音会话在 UI 中可见的状态。"""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


_ALLOWED_TRANSITIONS = {
    VoiceState.IDLE: {VoiceState.LISTENING},
    VoiceState.LISTENING: {VoiceState.THINKING, VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.THINKING: {VoiceState.SPEAKING, VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.SPEAKING: {VoiceState.LISTENING, VoiceState.IDLE, VoiceState.ERROR},
    VoiceState.ERROR: {VoiceState.IDLE, VoiceState.LISTENING},
}


@dataclass
class VoiceStateMachine:
    """管理单个 Streamlit session 的语音状态。"""

    state: VoiceState = VoiceState.IDLE
    error_message: str = ""

    def move_to(self, target: VoiceState) -> None:
        """迁移到目标状态，非法迁移会明确报错。"""
        if target not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"不支持的语音状态迁移: {self.state} -> {target}")
        self.state = target
        self.error_message = ""

    def fail(self, message: str) -> None:
        """进入错误状态并保存适合展示给用户的错误说明。"""
        self.state = VoiceState.ERROR
        self.error_message = message

    def reset(self) -> None:
        """回到空闲状态。"""
        self.state = VoiceState.IDLE
        self.error_message = ""
