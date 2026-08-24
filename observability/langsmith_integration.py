"""LangSmith 可选集成。

 LangGraph/LangChain 会根据 LANGSMITH_TRACING 自动发送 trace。本模块负责统一
配置校验、采样、敏感字段过滤和 RunnableConfig metadata；未配置 LangSmith 时完全 no-op。
"""

from __future__ import annotations

import os
import random
from collections.abc import Mapping
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def enabled() -> bool:
    tracing = os.getenv("LANGSMITH_TRACING", "false")
    api_key = os.getenv("LANGSMITH_API_KEY")
    return tracing.lower() in {"1", "true", "yes", "on"} and bool(api_key)


def sampled() -> bool:
    try:
        rate = max(0.0, min(1.0, float(os.getenv("LANGSMITH_SAMPLING_RATE", "1"))))
    except ValueError:
        rate = 1.0
    return enabled() and random.random() <= rate


def configure() -> bool:
    """校验并返回当前是否会发送 LangSmith trace。"""
    if not enabled():
        return False
    project = os.getenv("LANGSMITH_PROJECT") or "MutiRoleAgent"
    os.environ.setdefault("LANGSMITH_PROJECT", project)
    return True


def safe_metadata(metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """只保留追踪关联字段，避免把密钥、完整文件内容和完整对话上传。"""
    source = metadata or {}
    allowed = {"trace_id", "run_id", "session_id", "thread_id", "route", "prompt_version", "model", "dataset_version"}
    result = {key: value for key, value in source.items() if key in allowed and value is not None}
    return result


def graph_config_metadata(*, trace_id: str | None = None, run_id: str | None = None, session_id: str | None = None, thread_id: str | None = None, route: str | None = None, prompt_version: str | None = None) -> dict[str, Any]:
    return safe_metadata({"trace_id": trace_id, "run_id": run_id, "session_id": session_id, "thread_id": thread_id, "route": route, "prompt_version": prompt_version})


def redact_text(value: Any, *, max_chars: int = 500) -> str:
    """用于日志/评测报告的短摘要，不上传完整敏感内容。"""
    text = str(value or "")
    for marker in ("sk-", "lsv2_", "DASHSCOPE_API_KEY", "LANGSMITH_API_KEY"):
        if marker in text:
            return "[REDACTED]"
    return text[:max_chars]
