"""防止 ``<think>`` 内容混入用户可见正文的流式过滤器。"""

from __future__ import annotations

from typing import Literal


ThinkFilterMode = Literal["strict", "leading-only", "disabled"]
OPEN_TAG = "<think>"
CLOSE_TAG = "</think>"


class ThinkStreamFilter:
    """按单条模型消息隔离的跨 chunk 状态机。"""

    def __init__(self, mode: ThinkFilterMode = "leading-only") -> None:
        self.mode = mode
        self._pending = ""
        self._thinking = ""
        self._inside_think = False
        self._leading_state: Literal["buffering", "filtering", "passthrough"] = "buffering"

    def push(self, chunk: str) -> str:
        if not chunk:
            return ""
        if self.mode == "disabled":
            return chunk
        if self.mode == "strict":
            return self._push_strict(chunk)
        if self._leading_state == "passthrough":
            return chunk
        if self._leading_state == "filtering":
            return self._push_strict(chunk)

        self._pending += chunk
        trimmed = self._pending.lstrip()
        lowered = trimmed.lower()
        if lowered.startswith(OPEN_TAG):
            self._leading_state = "filtering"
            buffered = self._pending
            self._pending = ""
            return self._push_strict(buffered)
        if trimmed and not trimmed.startswith("<"):
            return self._start_passthrough()
        if len(trimmed) >= len(OPEN_TAG) and not lowered.startswith(OPEN_TAG):
            return self._start_passthrough()
        return ""

    def flush(self) -> str:
        if self.mode == "disabled" or self._leading_state == "passthrough":
            return ""
        if self.mode == "leading-only" and self._leading_state == "buffering":
            return self._start_passthrough()
        if self._inside_think:
            self._thinking += self._pending
            self._pending = ""
            return ""
        remaining = self._pending
        self._pending = ""
        return remaining

    def take_thinking(self) -> str:
        thinking = self._thinking
        self._thinking = ""
        return thinking

    def _start_passthrough(self) -> str:
        self._leading_state = "passthrough"
        buffered = self._pending
        self._pending = ""
        return buffered

    def _push_strict(self, chunk: str) -> str:
        self._pending += chunk
        visible = ""
        while self._pending:
            lowered = self._pending.lower()
            if self._inside_think:
                close_index = lowered.find(CLOSE_TAG)
                if close_index < 0:
                    safe_length = max(0, len(self._pending) - len(CLOSE_TAG) + 1)
                    self._thinking += self._pending[:safe_length]
                    self._pending = self._pending[safe_length:]
                    break
                self._thinking += self._pending[:close_index]
                self._pending = self._pending[close_index + len(CLOSE_TAG):]
                self._inside_think = False
                continue

            open_index = lowered.find(OPEN_TAG)
            if open_index < 0:
                safe_length = max(0, len(self._pending) - len(OPEN_TAG) + 1)
                visible += self._pending[:safe_length]
                self._pending = self._pending[safe_length:]
                break
            visible += self._pending[:open_index]
            self._pending = self._pending[open_index + len(OPEN_TAG):]
            self._inside_think = True
        return visible
