"""
CITA 2.0 Token 预算管理器
=========================
按优先级在各层之间分配 Token 预算，实时追踪使用量，
超限时触发 Reducer 裁剪。

预算分配策略::

    ┌──────────────────────────────────────────────┐
    │ Token 总预算 (默认 8000)                      │
    │                                              │
    │  System Prompt   ≤ 30%  (工具规则+安全+输出) │
    │  Persona Overlay ≤ 15%  (角色人设+世界观)    │
    │  History         ≤ 35%  (对话历史)           │
    │  Skill 指令      ≤ 20%  (工具使用说明)       │
    │                                              │
    │  各层独立追踪，超限时通知 Reducer             │
    └──────────────────────────────────────────────┘

使用方式::

    from agent.cita.budget import TokenBudget, BudgetStatus

    budget = TokenBudget(total_budget=8000)
    budget.track("system_prompt", 1200)
    budget.track("persona_overlay", 600)
    status = budget.check()
    if status == BudgetStatus.WARNING:
        # 触发 Reducer
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from utils.config_handler import load_decision_config
from utils.logger_handler import logger

# 加载 CITA 配置
def _load_cita_config():
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/cita.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except Exception:
        return {}

_CITA_CFG = _load_cita_config()
_BUDGET_CFG = _CITA_CFG.get("budget", {})


# ==================== 枚举 ====================

class BudgetStatus(Enum):
    """预算状态。"""
    OK = "ok"               # 正常
    WARNING = "warning"     # 超过警告阈值，建议裁剪
    CRITICAL = "critical"   # 超过紧急阈值，必须裁剪
    EXCEEDED = "exceeded"   # 超过总预算


# ==================== 数据结构 ====================

@dataclass
class LayerBudget:
    """单层预算信息。"""
    name: str                       # 层名称
    max_ratio: float                # 最大占比
    max_tokens: int = 0             # 最大 token 数
    used_tokens: int = 0            # 已使用 token 数
    item_count: int = 0             # 追踪项数量

    @property
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def usage_ratio(self) -> float:
        return self.used_tokens / self.max_tokens if self.max_tokens > 0 else 0.0


@dataclass
class BudgetSnapshot:
    """预算快照（用于日志和 UI 展示）。"""
    total_budget: int
    total_used: int
    status: BudgetStatus
    layers: dict[str, LayerBudget]
    timestamp: float = 0.0


# ==================== Token 估算 ====================

# 尝试加载 tiktoken
try:
    import tiktoken
    _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")  # GPT-4/4o 编码
    _HAS_TIKTOKEN = True
except ImportError:
    _TIKTOKEN_ENC = None
    _HAS_TIKTOKEN = False


def estimate_tokens(text: str, method: str = "auto") -> int:
    """估算文本的 token 数量。

    优先使用 tiktoken（精确），不可用时降级为字符估算（快速）。

    Args:
        text: 待估算文本。
        method: ``"tiktoken"`` / ``"char"`` / ``"auto"``（自动选择）。

    Returns:
        估算的 token 数。
    """
    if not text:
        return 0

    if method == "tiktoken" and _HAS_TIKTOKEN:
        return len(_TIKTOKEN_ENC.encode(text))
    elif method == "char":
        return _char_estimate(text)
    elif method == "auto":
        if _HAS_TIKTOKEN:
            return len(_TIKTOKEN_ENC.encode(text))
        else:
            return _char_estimate(text)
    return _char_estimate(text)


def _char_estimate(text: str) -> int:
    """基于字符类型的快速 token 估算（与 context_trimmer 保持一致）。"""
    chinese_chars = 0
    other_chars = 0

    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            chinese_chars += 1
        else:
            other_chars += 1

    estimated = chinese_chars * 0.8 + other_chars * 0.25
    return max(1, int(estimated) + 1)


def estimate_messages_tokens(messages: list) -> int:
    """估算消息列表的 token 总数。"""
    total = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    total += estimate_tokens(block["text"])
    return total


# ==================== Token 预算管理器 ====================

# 默认各层分配比例
_DEFAULT_ALLOCATION = {
    "system_prompt": 0.30,
    "persona_overlay": 0.15,
    "history": 0.35,
    "skill_instruction": 0.20,
}


class TokenBudget:
    """Token 预算管理器。

    追踪各层的 token 使用量，在超限时发出警告/紧急信号。

    使用示例::

        budget = TokenBudget(total_budget=8000)
        budget.track("system_prompt", 1200)
        budget.track("persona_overlay", 500)
        budget.track("history", estimate_messages_tokens(history))
        budget.track("skill_instruction", 300)

        if budget.status == BudgetStatus.CRITICAL:
            # 紧急裁剪
            ...
    """

    def __init__(
        self,
        total_budget: int | None = None,
        allocation: dict[str, float] | None = None,
    ):
        """
        Args:
            total_budget: 总 token 预算。None 则从 cita.yaml 读取，默认 8000。
            allocation: 各层分配比例。None 则从 cita.yaml 读取。
        """
        cfg_total = _BUDGET_CFG.get("total_budget", 8000)
        self.total_budget = total_budget if total_budget is not None else cfg_total

        cfg_allocation = _BUDGET_CFG.get("allocation", {})
        if not cfg_allocation:
            cfg_allocation = _DEFAULT_ALLOCATION
        self._allocation_ratios = allocation if allocation is not None else cfg_allocation

        self._warning_threshold = _BUDGET_CFG.get("warning_threshold", 0.75)
        self._critical_threshold = _BUDGET_CFG.get("critical_threshold", 0.90)

        # 初始化各层
        self.layers: dict[str, LayerBudget] = {}
        for name, ratio in self._allocation_ratios.items():
            self.layers[name] = LayerBudget(
                name=name,
                max_ratio=ratio,
                max_tokens=int(self.total_budget * ratio),
            )

        # 历史记录
        self._snapshots: list[BudgetSnapshot] = []

    # ==================== 追踪 ====================

    def track(self, layer: str, tokens: int, item_label: str = ""):
        """记录某层的 token 使用量。

        Args:
            layer: 层名称（system_prompt / persona_overlay / history / skill_instruction）。
            tokens: 使用的 token 数。
            item_label: 可选的追踪项标签（用于调试）。
        """
        if layer not in self.layers:
            logger.warning(f"[Budget] 未知层: {layer}，自动注册")
            self.layers[layer] = LayerBudget(
                name=layer,
                max_ratio=0.0,
                max_tokens=0,
            )

        lb = self.layers[layer]
        lb.used_tokens += tokens
        lb.item_count += 1

        logger.debug(
            f"[Budget] track {layer}: +{tokens} tokens "
            f"(used={lb.used_tokens}/{lb.max_tokens}, "
            f"{lb.usage_ratio:.0%})"
            f"{' [' + item_label + ']' if item_label else ''}"
        )

    def set_used(self, layer: str, tokens: int):
        """直接设置某层的已使用量（覆盖而非累加）。"""
        if layer not in self.layers:
            self.layers[layer] = LayerBudget(
                name=layer, max_ratio=0.0, max_tokens=0,
            )
        self.layers[layer].used_tokens = tokens

    def reset(self):
        """重置所有层的使用量。"""
        for lb in self.layers.values():
            lb.used_tokens = 0
            lb.item_count = 0

    # ==================== 查询 ====================

    @property
    def total_used(self) -> int:
        return sum(lb.used_tokens for lb in self.layers.values())

    @property
    def total_remaining(self) -> int:
        return max(0, self.total_budget - self.total_used)

    @property
    def usage_ratio(self) -> float:
        return self.total_used / self.total_budget if self.total_budget > 0 else 0.0

    @property
    def status(self) -> BudgetStatus:
        """当前预算状态。"""
        ratio = self.usage_ratio
        if ratio >= 1.0:
            return BudgetStatus.EXCEEDED
        if ratio >= self._critical_threshold:
            return BudgetStatus.CRITICAL
        if ratio >= self._warning_threshold:
            return BudgetStatus.WARNING
        return BudgetStatus.OK

    def get_layer(self, layer: str) -> LayerBudget | None:
        """获取指定层的预算信息。"""
        return self.layers.get(layer)

    def available_for(self, layer: str) -> int:
        """返回某层还可使用的 token 数。"""
        lb = self.layers.get(layer)
        if lb is None:
            return 0
        return lb.remaining

    def can_add(self, layer: str, tokens: int) -> bool:
        """检查某层是否能容纳指定 token 数。"""
        return self.available_for(layer) >= tokens

    # ==================== 超标层检测 ====================

    def over_budget_layers(self) -> list[str]:
        """返回已超标的层名称列表。"""
        return [
            name for name, lb in self.layers.items()
            if lb.max_tokens > 0 and lb.used_tokens > lb.max_tokens
        ]

    def critical_layers(self) -> list[str]:
        """返回达到紧急阈值的层名称列表。"""
        return [
            name for name, lb in self.layers.items()
            if lb.max_tokens > 0 and lb.usage_ratio >= self._critical_threshold
        ]

    # ==================== 快照 ====================

    def snapshot(self) -> BudgetSnapshot:
        """生成当前预算快照。"""
        import time
        layers_copy = {
            name: LayerBudget(
                name=lb.name,
                max_ratio=lb.max_ratio,
                max_tokens=lb.max_tokens,
                used_tokens=lb.used_tokens,
                item_count=lb.item_count,
            )
            for name, lb in self.layers.items()
        }
        snap = BudgetSnapshot(
            total_budget=self.total_budget,
            total_used=self.total_used,
            status=self.status,
            layers=layers_copy,
            timestamp=time.time(),
        )
        self._snapshots.append(snap)
        # 只保留最近 20 个快照
        if len(self._snapshots) > 20:
            self._snapshots = self._snapshots[-20:]
        return snap

    # ==================== 展示 ====================

    def format_summary(self) -> str:
        """格式化预算摘要（用于 Streamlit 侧边栏或日志）。"""
        lines = [
            f"Token Budget: {self.total_used}/{self.total_budget} ({self.usage_ratio:.0%})",
            f"Status: {self.status.value.upper()}",
            "",
        ]
        for name, lb in self.layers.items():
            bar_len = 20
            filled = int(bar_len * lb.usage_ratio) if lb.max_tokens > 0 else 0
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(
                f"  {name:20s} {bar} {lb.used_tokens:>5d}/{lb.max_tokens:>5d} ({lb.usage_ratio:.0%})"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """导出为字典（方便 JSON 序列化 / Streamlit 展示）。"""
        return {
            "total_budget": self.total_budget,
            "total_used": self.total_used,
            "total_remaining": self.total_remaining,
            "usage_ratio": round(self.usage_ratio, 3),
            "status": self.status.value,
            "layers": {
                name: {
                    "max_tokens": lb.max_tokens,
                    "used_tokens": lb.used_tokens,
                    "remaining": lb.remaining,
                    "usage_ratio": round(lb.usage_ratio, 3),
                    "item_count": lb.item_count,
                }
                for name, lb in self.layers.items()
            },
        }

    def __repr__(self) -> str:
        return (
            f"TokenBudget(total={self.total_budget}, "
            f"used={self.total_used}, status={self.status.value})"
        )


# ==================== 模块级便捷实例 ====================

# 每轮对话创建新实例（不全局共享）
def create_budget(total_budget: int | None = None) -> TokenBudget:
    """创建一个新的 TokenBudget 实例。

    Args:
        total_budget: 总 token 预算。None 则从配置读取。

    Returns:
        新的 TokenBudget 实例。
    """
    return TokenBudget(total_budget=total_budget)


# ==================== 测试 ====================

if __name__ == "__main__":
    budget = TokenBudget(total_budget=8000)

    # 模拟各层追踪
    budget.track("system_prompt", 1200, "tool_rules+safety+output")
    budget.track("persona_overlay", 600, "Cyrene_default")
    budget.track("history", 2000, "10_rounds")
    budget.track("skill_instruction", 400, "anime_skills")

    print(budget.format_summary())
    print(f"\nStatus: {budget.status.value}")
    print(f"Over-budget layers: {budget.over_budget_layers()}")
    print(f"Available for history: {budget.available_for('history')}")

    # 测试超标
    budget.track("history", 5000, "more_history")
    print(f"\nAfter adding more history:")
    print(f"Status: {budget.status.value}")
    print(f"Over-budget layers: {budget.over_budget_layers()}")

    # 导出
    import json
    print(f"\nJSON: {json.dumps(budget.to_dict(), indent=2, ensure_ascii=False)}")
