"""Agent performance metrics for one cached conversation session."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class PerformanceSnapshot:
    """Cumulative metrics exposed to the UI."""

    task_rounds: int = 0
    execution_steps: int = 0
    llm_duration_seconds: float = 0.0
    tool_duration_seconds: float = 0.0
    ttft_seconds: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    visible_output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_input_tokens: int = 0
    cache_metrics_available: bool = False
    output_tokens_per_second: float = 0.0
    llm_calls: int = 0
    completed_rounds: int = 0
    failed_rounds: int = 0
    timed_out_rounds: int = 0
    rejected_rounds: int = 0
    tool_calls: int = 0
    tool_failures: int = 0

    @property
    def cache_hit_rate(self) -> float | None:
        if not self.cache_metrics_available or self.cache_input_tokens <= 0:
            return None
        return min(1.0, self.cache_read_tokens / self.cache_input_tokens)


class PerformanceMonitor:
    """Collect metrics without coupling the UI to LangGraph internals."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = PerformanceSnapshot()
        self._turn_started_at = 0.0
        self._first_token_at: float | None = None
        self._turn_output_tokens = 0

    def start_turn(self) -> None:
        with self._lock:
            self._turn_started_at = time.perf_counter()
            self._first_token_at = None
            self._turn_output_tokens = 0
            self._snapshot.task_rounds += 1

    def finish_turn(self, outcome: str = "success") -> None:
        with self._lock:
            if self._first_token_at is not None:
                elapsed = time.perf_counter() - self._first_token_at
                if self._turn_output_tokens > 0 and elapsed > 0:
                    self._snapshot.output_tokens_per_second = (
                        self._turn_output_tokens / elapsed
                    )
            self._snapshot.completed_rounds += 1
            if outcome == "error":
                self._snapshot.failed_rounds += 1
            elif outcome == "timeout":
                self._snapshot.timed_out_rounds += 1
            elif outcome == "rejected":
                self._snapshot.rejected_rounds += 1

    def record_step(self, count: int = 1) -> None:
        with self._lock:
            self._snapshot.execution_steps += count

    def record_rejection(self) -> None:
        """记录因同会话并发而被拒绝的请求。"""
        with self._lock:
            self._snapshot.rejected_rounds += 1

    def record_llm_call(
        self,
        duration_seconds: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_input_tokens: int = 0,
        cache_metrics_available: bool = False,
    ) -> None:
        with self._lock:
            self._snapshot.llm_duration_seconds += max(0.0, duration_seconds)
            self._snapshot.llm_calls += 1
            self._snapshot.input_tokens += max(0, input_tokens)
            self._snapshot.output_tokens += max(0, output_tokens)
            self._snapshot.cache_read_tokens += max(0, cache_read_tokens)
            self._snapshot.cache_input_tokens += max(0, cache_input_tokens)
            self._snapshot.cache_metrics_available |= cache_metrics_available
            self._turn_output_tokens += max(0, output_tokens)

    def record_tool_call(self, duration_seconds: float, success: bool = True) -> None:
        with self._lock:
            self._snapshot.tool_duration_seconds += max(0.0, duration_seconds)
            self._snapshot.tool_calls += 1
            if not success:
                self._snapshot.tool_failures += 1

    def record_visible_text(self, token_count: int) -> None:
        with self._lock:
            if self._first_token_at is None:
                self._first_token_at = time.perf_counter()
                self._snapshot.ttft_seconds = (
                    self._first_token_at - self._turn_started_at
                )
            tokens = max(0, token_count)
            self._snapshot.visible_output_tokens += tokens
            if self._turn_output_tokens == 0:
                self._turn_output_tokens = tokens

    def snapshot(self) -> PerformanceSnapshot:
        with self._lock:
            return PerformanceSnapshot(**self._snapshot.__dict__)
