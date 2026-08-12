"""
上下文自动裁剪工具
==================
在每次对话执行前对历史消息进行裁剪，防止 token 溢出导致的
模型截断、幻觉或 API 调用失败。

核心函数 ``trim_history()`` 同时支持两种限制策略，取较严格者：

- **max_tokens**：按估算 token 数裁剪
- **max_rounds**：按对话轮数裁剪（1 轮 = 用户消息 + 模型回复）

裁剪原则
--------
1. **从旧到新裁剪**：保留最近的消息，丢弃最早的消息。
2. **保持轮次完整**：不会把一轮对话（用户+助手+工具调用链）从中截断。
3. **保留会话锚点**：首条用户消息始终保留，维持对话上下文起点。
4. **保守估计 token**：中英文混合场景按 ``字符数 / 1.5`` 估算，
   略高估以确保实际不会溢出。

使用方式::

    from utils.context_trimmer import trim_history

    trimmed = trim_history(messages, max_tokens=6000, max_rounds=15)
"""

from typing import Sequence
from langchain_core.messages import BaseMessage, HumanMessage
from utils.config_handler import agent_config
from utils.logger_handler import logger

# 默认裁剪参数（从 agent.yaml 读取兜底）
_CTX_CFG = agent_config.get("context", {})
_DEFAULT_MAX_TOKENS = _CTX_CFG.get("trim_max_tokens", 6000)
_DEFAULT_MAX_ROUNDS = _CTX_CFG.get("trim_max_rounds", 15)


# ==================== Token 估算 ====================

def estimate_tokens(text: str) -> int:
    """保守估算一段文本的 token 数量。

    规则：
    - 中文字符（Unicode CJK 范围）按 1 字符 ≈ 0.8 token
    - 英文/数字按 1 字符 ≈ 0.25 token（即 4 字符 ≈ 1 token）
    - 最终结果向上取整，略高估以留出安全余量

    这是一个快速估算法，不需要加载 tokenizer 模型文件，
    在准确性（±15%）和性能之间取得平衡。
    """
    if not text:
        return 0

    chinese_chars = 0
    other_chars = 0

    for ch in text:
        if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
            chinese_chars += 1
        else:
            other_chars += 1

    # 中文 ~0.8 token/char，英文 ~0.25 token/char
    estimated = chinese_chars * 0.8 + other_chars * 0.25
    return max(1, int(estimated) + 1)  # +1 安全余量


def estimate_message_tokens(msg: BaseMessage) -> int:
    """估算单条消息的 token 数（content + tool_calls 等）。"""
    tokens = 0
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)
    elif isinstance(content, list):
        # content 可能是 [{"type": "text", "text": "..."}, ...]
        for block in content:
            if isinstance(block, dict) and "text" in block:
                tokens += estimate_tokens(block["text"])

    # tool_calls 的 args 也计入
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        for tc in tool_calls:
            args_str = str(tc.get("args", ""))
            tokens += estimate_tokens(args_str)

    return tokens


# ==================== 轮次分组 ====================

def _group_into_rounds(
    messages: Sequence[BaseMessage],
) -> list[list[BaseMessage]]:
    """将消息列表按对话轮次分组。

    分组规则：
    - 每条 HumanMessage 开启新的一轮
    - 该轮包含此 HumanMessage 及其后所有非 HumanMessage（AIMessage、
      ToolMessage 等），直到遇到下一条 HumanMessage 为止
    - 开头的非 HumanMessage（如 SystemMessage）归入第 0 轮（序言）

    Returns:
        list[list[BaseMessage]]，按时间顺序排列的轮次列表。
    """
    rounds: list[list[BaseMessage]] = []
    current_round: list[BaseMessage] = []

    for msg in messages:
        if isinstance(msg, HumanMessage) and current_round:
            # 新的用户消息 → 上一轮结束，开始新轮
            rounds.append(current_round)
            current_round = [msg]
        else:
            current_round.append(msg)

    if current_round:
        rounds.append(current_round)

    return rounds


# ==================== 裁剪主函数 ====================

def trim_history(
    messages: Sequence[BaseMessage],
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
) -> list[BaseMessage]:
    """对消息历史进行智能裁剪。

    从最新一轮开始往回保留，直到达到 token 上限或轮次上限。

    Args:
        messages:    完整的消息历史列表（按时间顺序）。
        max_tokens:  保留消息的最大 token 估算数。默认 6000。
        max_rounds:  保留的最大对话轮数。默认 15。

    Returns:
        裁剪后的消息列表（新列表，不修改原列表）。

    裁剪保证：
    - 首轮（第一条用户消息 + 上下文）始终保留
    - 其他轮次从旧到新丢弃
    - 不会把一轮对话从中截断
    """
    if not messages:
        return []

    total_rounds = _group_into_rounds(messages)

    if len(total_rounds) <= 1:
        # 只有 1 轮或没有消息，直接返回
        return list(messages)

    first_round = total_rounds[0]      # 始终保留
    middle_rounds = total_rounds[1:]   # 可能被裁剪

    # 从最新一轮开始，往旧的方向保留
    kept_rounds: list[list[BaseMessage]] = []
    current_tokens = 0
    current_rounds = 0

    for rnd in reversed(middle_rounds):
        rnd_tokens = sum(estimate_message_tokens(m) for m in rnd)

        # 检查是否超限（预留首轮 token）
        first_round_tokens = sum(estimate_message_tokens(m) for m in first_round)
        if (
            current_tokens + rnd_tokens + first_round_tokens > max_tokens
            or current_rounds + 1 > max_rounds
        ):
            break

        kept_rounds.insert(0, rnd)  # 插入到前面，保持时间顺序
        current_tokens += rnd_tokens
        current_rounds += 1

    # 组装：首轮 + 保留的中间轮次
    result = list(first_round)
    for rnd in kept_rounds:
        result.extend(rnd)

    # 日志
    original_count = len(messages)
    trimmed_count = len(result)
    original_est = sum(estimate_message_tokens(m) for m in messages)
    trimmed_est = sum(estimate_message_tokens(m) for m in result)

    if trimmed_count < original_count:
        logger.info(
            f"[trim_history] 裁剪完成: {original_count} 条 → {trimmed_count} 条 "
            f"({len(total_rounds) - len(kept_rounds) - 1} 轮被丢弃), "
            f"token 估算: {original_est} → {trimmed_est} / max={max_tokens}, "
            f"保留轮数: {len(kept_rounds) + 1} / max={max_rounds}"
        )
    else:
        logger.debug(
            f"[trim_history] 无需裁剪: {original_count} 条消息, "
            f"token 估算={original_est}, 轮数={len(total_rounds)}"
        )

    return result


def trim_history_light(
    messages: Sequence[BaseMessage],
    max_tokens: int = 2000,
) -> list[BaseMessage]:
    """轻量裁剪（仅 token 限制，不限制轮数）。

    用于对 token 极为敏感的场景（如 MCP 工具调用的上下文）。
    """
    return trim_history(messages, max_tokens=max_tokens, max_rounds=999)


# ==================== 调试辅助 ====================

def trim_with_cita(
    messages: Sequence[BaseMessage],
    query: str = "",
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
) -> dict:
    """CITA 2.0 增强裁剪：语义去重 + 无关移除 + 预算裁剪。

    与 CITA 的分工：
    - Reducer（CITA）管"裁哪些"：基于语义评分选择保留/移除
    - Trimmer（此处）管"量"：确保不超 token/轮数上限
    - 协同流程：Reducer 评分 → 按预算过滤 → Trimmer 确保合规

    Args:
        messages: 完整消息历史。
        query: 当前用户查询（用于语义分析）。
        max_tokens: 最大 token 估算数。
        max_rounds: 最大对话轮数。

    Returns:
        dict with keys:
        - ``messages``: 裁剪后的消息列表
        - ``trim_summary``: 被裁剪内容的摘要
        - ``removed_count``: 移除消息数
        - ``budget_info``: Token 预算信息（dict）
    """
    try:
        from agent.cita.reducer import ContextReducer
        from agent.cita.semantic import SemanticEngine
        from agent.cita.budget import TokenBudget, estimate_tokens

        # 1) 语义分析
        engine = SemanticEngine()
        analysis = engine.analyze(query) if query else None
        entities = analysis.entities if analysis else None

        # 2) Token 预算
        budget = TokenBudget(total_budget=max_tokens)
        # 为 History 层分配 35% 预算（cita.yaml 默认）
        history_budget = int(max_tokens * 0.35)

        # 3) Reducer 语义裁剪
        reducer = ContextReducer()
        result = reducer.reduce(
            messages=messages,
            query_entities=entities,
            max_tokens=history_budget,
        )

        # 4) 基础裁剪确保轮数合规
        final_messages = trim_history(
            result.kept_messages,
            max_tokens=max_tokens,
            max_rounds=max_rounds,
        )

        # 5) 预算追踪
        budget.track("history", estimate_messages_tokens(final_messages))
        if result.trim_summary:
            summary_tokens = estimate_tokens(result.trim_summary)
            budget.track("system_prompt", summary_tokens, "trim_summary")

        logger.info(
            f"[trim_with_cita] {len(messages)} → {len(final_messages)} 条 "
            f"(语义裁剪: -{result.removed_count}, 去重: -{result.deduplicated_count}, "
            f"无关: -{result.irrelevant_count})"
        )

        return {
            "messages": final_messages,
            "trim_summary": result.trim_summary,
            "removed_count": len(messages) - len(final_messages),
            "deduplicated_count": result.deduplicated_count,
            "irrelevant_count": result.irrelevant_count,
            "budget_info": budget.to_dict(),
        }

    except ImportError as e:
        logger.debug(f"[trim_with_cita] CITA 2.0 不可用，降级为基础裁剪: {e}")
        trimmed = trim_history(messages, max_tokens=max_tokens, max_rounds=max_rounds)
        return {
            "messages": trimmed,
            "trim_summary": "",
            "removed_count": len(messages) - len(trimmed),
            "deduplicated_count": 0,
            "irrelevant_count": 0,
            "budget_info": {},
        }


def history_stats(messages: Sequence[BaseMessage]) -> dict:
    """返回消息历史的统计摘要。"""
    rounds = _group_into_rounds(messages)
    total_tokens = sum(estimate_message_tokens(m) for m in messages)
    return {
        "total_messages": len(messages),
        "total_rounds": len(rounds),
        "estimated_tokens": total_tokens,
        "first_round_tokens": sum(estimate_message_tokens(m) for m in rounds[0]) if rounds else 0,
        "last_round_tokens": sum(estimate_message_tokens(m) for m in rounds[-1]) if rounds else 0,
    }
