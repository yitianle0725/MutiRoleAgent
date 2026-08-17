"""Tests for model usage metadata normalization."""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import AIMessage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.react_agent import _token_usage
from utils.performance_monitor import PerformanceMonitor


def test_token_usage_reads_langchain_usage_metadata() -> None:
    message = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
    )
    usage = _token_usage(message)
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 4
    assert usage["total_tokens"] == 14


def test_token_usage_reads_openai_compatible_metadata() -> None:
    message = AIMessage(
        content="ok",
        response_metadata={"token_usage": {"prompt_tokens": 9, "completion_tokens": 3}},
    )
    usage = _token_usage(message)
    assert usage["input_tokens"] == 9
    assert usage["output_tokens"] == 3


def test_cache_rate_is_unknown_without_provider_cache_fields() -> None:
    monitor = PerformanceMonitor()
    monitor.record_llm_call(0.1, input_tokens=10, output_tokens=2)
    assert monitor.snapshot().cache_hit_rate is None
