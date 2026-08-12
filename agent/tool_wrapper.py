"""
工具执行统一包装器
==================
为所有本地工具调用提供统一的超时控制、异常捕获和耗时日志。
超时配置从 config/agent.yaml 读取。
"""

import time
import concurrent.futures
from typing import Callable

from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from utils.config_handler import agent_config
from utils.logger_handler import logger


# ==================== 默认超时配置（从 agent.yaml 读取） ====================

_TIMEOUT_CFG = agent_config.get("tool_timeouts", {})
DEFAULT_TIMEOUTS: dict[str, float] = {
    k: float(v) for k, v in _TIMEOUT_CFG.items() if k != "default"
}
_DEFAULT_TIMEOUT = float(_TIMEOUT_CFG.get("default", 10.0))


# ==================== 包装函数 ====================

def execute_with_safety(
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
    request: ToolCallRequest,
    tool_name: str,
    tool_call_id: str = "",
    timeout: float | None = None,
) -> ToolMessage:
    """统一包装工具执行：超时控制 + 异常捕获 + 耗时日志。"""
    effective_timeout = timeout or DEFAULT_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT)
    start_time = time.perf_counter()
    tool_call_id = tool_call_id or request.tool_call.get("id", "")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(handler, request)
            result = future.result(timeout=effective_timeout)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            f"[tool wrapper] {tool_name} 执行成功 | 耗时: {elapsed_ms:.0f}ms"
        )
        return result

    except concurrent.futures.TimeoutError:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            f"[tool wrapper] {tool_name} 执行超时 "
            f"(限制={effective_timeout}s, 实际耗时={elapsed_ms:.0f}ms)"
        )
        return ToolMessage(
            content=(
                f"[工具超时] 工具 '{tool_name}' 在 {effective_timeout} 秒内未响应。"
                f"请尝试简化参数或稍后重试。"
            ),
            tool_call_id=tool_call_id,
        )

    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        error_type = type(e).__name__
        logger.error(
            f"[tool wrapper] {tool_name} 执行失败 | "
            f"异常类型: {error_type} | "
            f"异常信息: {str(e)[:200]} | "
            f"耗时: {elapsed_ms:.0f}ms"
        )
        return ToolMessage(
            content=(
                f"[工具执行失败] 工具 '{tool_name}' 执行时发生错误 "
                f"({error_type}: {str(e)[:150]})。"
                f"请尝试更换参数或使用其他工具完成当前任务。"
            ),
            tool_call_id=tool_call_id,
        )


def get_tool_timeout(tool_name: str) -> float:
    """查询指定工具的默认超时时间。"""
    return DEFAULT_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT)
