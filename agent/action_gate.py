"""
Action Gate 门控模块
====================
在工具加载和运行时两个阶段拦截危险/未授权工具调用。

职责
----
1. **加载时过滤**：``filter_tools()`` —— 去除非白名单 MCP 工具 + 拦截危险工具名
2. **运行时检查**：``check_tool_call()`` —— 参数路径穿越检测 + 权限校验

使用方式::

    from agent.action_gate import action_gate

    # 加载时过滤
    safe_tools = action_gate.filter_tools(all_tools, context={"user_id": "1001"})

    # 运行时检查
    result = action_gate.check_tool_call("rag_summarize", {"query": "..."})
    if not result.allow:
        return ToolMessage(content=f"[工具调用被拒绝] {result.reason}", ...)
"""

import re
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from utils.config_handler import gate_config
from utils.logger_handler import logger


# ==================== 数据结构 ====================

@dataclass
class GateResult:
    """Gate 检查结果。

    Attributes:
        allow: 是否允许执行。
        reason: 拒绝原因（allow=False 时必填）。
    """
    allow: bool = True
    reason: str = ""


# ==================== 模块级常量（从配置加载） ====================

def _build_blocked_patterns() -> list[re.Pattern]:
    """从 YAML 配置编译危险关键词正则列表。"""
    patterns: list[str] = gate_config.get("blocked_name_patterns", [])
    return [re.compile(p, re.IGNORECASE) for p in patterns]


# 路径穿越检测正则
_PATH_TRAVERSAL_RE = re.compile(r'\.\./|\.\.\\')

# 危险工具名正则（从配置构建）
_BLOCKED_NAME_PATTERNS: list[re.Pattern] = _build_blocked_patterns()

# MCP 工具白名单
_MCP_WHITELIST: set[str] = set(gate_config.get("mcp_tool_whitelist", []))

# 工具分类
_SAFE_TOOLS: set[str] = {
    "rag_summarize", "get_weather", "get_user_location",
    "get_public_ip",
}

_STATEFUL_TOOLS: set[str] = {
    "switch_persona", "reset_persona",
}

_AUTH_REQUIRED_TOOLS: set[str] = set()


# ==================== ActionGate ====================

class ActionGate:
    """工具门控：加载时过滤 + 运行时拦截。

    不依赖任何外部状态，所有配置从 YAML 文件加载。
    """

    # ---- 辅助方法 ----

    @staticmethod
    def _is_local_tool(tool: BaseTool) -> bool:
        """判断工具是否为项目本地工具（非 MCP 远端工具）。

        判断依据：MCP 工具通常携带 ``__mcp_server__`` metadata，
        本地工具则没有，或者 metadata 为空。
        """
        metadata = getattr(tool, 'metadata', None)
        if metadata is None:
            return True
        if isinstance(metadata, dict):
            return "__mcp_server__" not in metadata
        return True

    @staticmethod
    def _has_dangerous_name(tool_name: str) -> str | None:
        """检查工具名是否匹配危险关键词。

        Returns:
            匹配到的关键词（首次命中），无匹配返回 None。
        """
        for pattern in _BLOCKED_NAME_PATTERNS:
            if pattern.search(tool_name):
                return pattern.pattern
        return None

    @staticmethod
    def _has_path_traversal(args: dict) -> bool:
        """递归检查参数值是否包含路径穿越（../ 或 ..\\）。"""
        for value in args.values():
            if isinstance(value, str) and _PATH_TRAVERSAL_RE.search(value):
                return True
            if isinstance(value, dict) and ActionGate._has_path_traversal(value):
                return True
        return False

    # ---- 加载时过滤 ----

    def filter_tools(
        self,
        all_tools: list[BaseTool],
        context: dict | None = None,
    ) -> list[BaseTool]:
        """加载阶段过滤工具列表。

        过滤规则（按优先级）：
        1. 危险工具名 → 直接移除
        2. MCP 工具不在白名单 → 移除
        3. 鉴权工具缺少上下文 → 降级（记录日志，仍保留）

        Args:
            all_tools: 完整的待注入工具列表。
            context: 运行时上下文，如 ``{"user_id": "1001"}``。

        Returns:
            过滤后的工具列表（不影响原列表）。
        """
        ctx = context or {}
        safe: list[BaseTool] = []
        removed: list[str] = []

        for tool in all_tools:
            tool_name = tool.name

            # 1) 危险工具名 → 移除
            dangerous = self._has_dangerous_name(tool_name)
            if dangerous:
                logger.warning(
                    f"[Action Gate] 移除危险工具: {tool_name} "
                    f"(匹配关键词: '{dangerous}')"
                )
                removed.append(f"{tool_name}(危险关键词:{dangerous})")
                continue

            # 2) MCP 工具白名单检查
            if not self._is_local_tool(tool):
                if tool_name not in _MCP_WHITELIST:
                    logger.warning(
                        f"[Action Gate] 移除未授权 MCP 工具: {tool_name} "
                        f"(不在白名单中)"
                    )
                    removed.append(f"{tool_name}(MCP未授权)")
                    continue

            # 3) 鉴权工具上下文检查
            if tool_name in _AUTH_REQUIRED_TOOLS:
                if not ctx.get("user_id"):
                    logger.info(
                        f"[Action Gate] 鉴权工具 {tool_name} 缺少 user_id，"
                        f"保留但可能降级"
                    )
                    # 不阻断——运行时由 middlewares 处理降级

            safe.append(tool)

        if removed:
            logger.info(
                f"[Action Gate] 工具过滤完成: {len(all_tools)} → {len(safe)}, "
                f"移除: {removed}"
            )
        else:
            logger.debug(
                f"[Action Gate] 工具过滤完成: {len(all_tools)} 个工具，无移除"
            )

        return safe

    # ---- 运行时拦截 ----

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict | None,
    ) -> GateResult:
        """运行时工具调用前检查。

        检查规则：
        1. 危险工具名 → 拒绝
        2. 参数路径穿越 → 拒绝
        3. 其他检查通过 → 放行

        Args:
            tool_name: 工具函数名。
            tool_args: 调用参数字典。

        Returns:
            ``GateResult``，``allow=True`` 表示放行。
        """
        args = tool_args or {}

        # 1) 危险工具名
        dangerous = self._has_dangerous_name(tool_name)
        if dangerous:
            reason = (
                f"工具 '{tool_name}' 包含危险关键词 '{dangerous}'，"
                f"已被系统拒绝。"
            )
            logger.warning(f"[Action Gate] 运行时拦截: {reason}")
            return GateResult(allow=False, reason=reason)

        # 2) 路径穿越
        if self._has_path_traversal(args):
            reason = (
                f"工具 '{tool_name}' 的参数包含路径穿越（../ 或 ..\\），"
                f"已被系统拒绝。"
            )
            logger.warning(f"[Action Gate] 路径穿越拦截: {reason}")
            return GateResult(allow=False, reason=reason)

        return GateResult(allow=True)


# ==================== 模块级单例 ====================

action_gate = ActionGate()
