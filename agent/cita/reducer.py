"""
CITA 2.0 上下文结构裁剪器
=========================
对对话历史进行语义级别的裁剪：去重、无关信息移除、摘要注入。

与 context_trimmer.py 的分工
---------------------------
- **CITA Reducer** 管"裁哪些"：基于语义理解选择保留/移除哪些消息
- **context_trimmer** 管"量"：按 token/轮数上限裁剪
- **协同流程**：SemanticEngine 分析 → Reducer 标记重要性 → Trimmer 按预算裁剪

裁剪策略
--------
1. **去重**：相似度 > 阈值的连续消息只保留最新一条
2. **无关信息移除**：纯表情、单字回复、重复追问标记为低价值
3. **摘要注入**：被裁剪的内容生成简短摘要，注入到保留的消息中
4. **重要性评分**：实体/问题/情绪/时效/长度 五维评分

使用方式::

    from agent.cita.reducer import ContextReducer

    reducer = ContextReducer()
    reduced, summary = reducer.reduce(
        messages=history,
        query_entities=analysis.entities,
        max_tokens=2800,  # 来自 TokenBudget
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence, Any

# langchain_core 可选依赖（仅类型标注和消息类型判断使用）
try:
    from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
    _HAS_LANGCHAIN = True
except ImportError:
    BaseMessage = Any  # type: ignore
    HumanMessage = Any  # type: ignore
    AIMessage = Any  # type: ignore
    _HAS_LANGCHAIN = False

from utils.logger_handler import logger

# CITA 配置
def _load_reducer_cfg():
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/cita.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader).get("reducer", {})
    except Exception:
        return {}

_REDUCER_CFG = _load_reducer_cfg()


# ==================== 数据结构 ====================

@dataclass
class MessageScore:
    """单条消息的重要性评分。"""
    index: int                       # 在原历史中的位置
    content: str                     # 消息文本
    total_score: float = 0.0         # 综合评分
    has_entity: bool = False         # 包含实体
    has_question: bool = False       # 包含问句
    has_emotion: bool = False        # 包含情绪
    is_recent: bool = False          # 是否为最近消息
    length_factor: float = 0.0       # 长度因子（过长或过短降权）
    is_duplicate: bool = False       # 是否为重复消息
    is_irrelevant: bool = False      # 是否为无关消息
    irrelevance_reason: str = ""     # 无关原因


@dataclass
class ReduceResult:
    """裁剪结果。"""
    kept_messages: list[BaseMessage]     # 保留的消息
    removed_count: int                    # 移除的消息数
    deduplicated_count: int              # 去重移除数
    irrelevant_count: int                # 无关移除数
    trim_summary: str                     # 被裁剪内容的摘要
    importance_scores: list[MessageScore] # 评分详情


# ==================== 重要性评分 ====================

# 评分权重
_IMPORTANCE_WEIGHTS = _REDUCER_CFG.get("importance_weights", {
    "has_entity": 0.30,
    "has_question": 0.25,
    "has_emotion": 0.20,
    "is_recent": 0.15,
    "length_factor": 0.10,
})


def _score_message(
    msg: BaseMessage,
    index: int,
    total_count: int,
    entities: list | None = None,
) -> MessageScore:
    """对单条消息进行重要性评分。

    评分维度：
    - has_entity: 消息中出现了当前查询的实体 → +0.30
    - has_question: 消息包含问句 → +0.25
    - has_emotion: 消息包含情绪表达 → +0.20
    - is_recent: 消息越新权重越高 → +0.15（按位置线性分配）
    - length_factor: 长度适中（20~500字）权重最高 → +0.10
    """
    content = _get_message_text(msg)
    score = MessageScore(index=index, content=content)

    # 1) 实体匹配
    if entities:
        for entity in entities:
            if hasattr(entity, 'value') and entity.value in content:
                score.has_entity = True
                break
    score.total_score += _IMPORTANCE_WEIGHTS["has_entity"] if score.has_entity else 0

    # 2) 问句检测
    if "?" in content or "？" in content or any(
        qw in content for qw in ["什么", "怎么", "如何", "为什么", "哪", "谁", "几"]
    ):
        score.has_question = True
    score.total_score += _IMPORTANCE_WEIGHTS["has_question"] if score.has_question else 0

    # 3) 情绪检测（简单版——关键词）
    emotion_kw = [
        "谢谢", "辛苦了", "开心", "难过", "烦", "气死", "急",
        "不懂", "不明白", "太好", "真棒", "喜欢", "讨厌",
    ]
    if any(kw in content for kw in emotion_kw):
        score.has_emotion = True
    score.total_score += _IMPORTANCE_WEIGHTS["has_emotion"] if score.has_emotion else 0

    # 4) 时效性（越新权重越高）
    if total_count > 1:
        recency = index / (total_count - 1)  # 0.0(最早) ~ 1.0(最新)
        score.is_recent = recency > 0.7
        score.total_score += _IMPORTANCE_WEIGHTS["is_recent"] * recency
    else:
        score.total_score += _IMPORTANCE_WEIGHTS["is_recent"]

    # 5) 长度因子（适中长度最好）
    text_len = len(content)
    if 20 <= text_len <= 500:
        score.length_factor = 1.0
    elif text_len < 20:
        score.length_factor = 0.3  # 太短价值低
    else:
        score.length_factor = 0.6  # 太长可能含冗余
    score.total_score += _IMPORTANCE_WEIGHTS["length_factor"] * score.length_factor

    return score


# ==================== 去重检测 ====================

def _dedup_threshold() -> float:
    return _REDUCER_CFG.get("dedup_threshold", 0.75)


def _similarity(text_a: str, text_b: str) -> float:
    """计算两段文本的简单相似度（Jaccard + 长度比）。"""
    if not text_a or not text_b:
        return 0.0

    # 完全一致
    if text_a == text_b:
        return 1.0

    # 字符级 Jaccard
    set_a = set(text_a)
    set_b = set(text_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    jaccard = len(set_a & set_b) / union

    # 长度比
    len_ratio = min(len(text_a), len(text_b)) / max(len(text_a), len(text_b), 1)

    # 综合（Jaccard 70% + 长度比 30%）
    return jaccard * 0.7 + len_ratio * 0.3


def _deduplicate(messages: list[BaseMessage]) -> tuple[list[BaseMessage], int]:
    """移除连续重复消息，保留最新的。"""
    if len(messages) <= 1:
        return messages, 0

    threshold = _dedup_threshold()
    kept: list[BaseMessage] = [messages[0]]
    removed = 0

    for i in range(1, len(messages)):
        prev_text = _get_message_text(messages[i - 1])
        curr_text = _get_message_text(messages[i])

        sim = _similarity(prev_text, curr_text)
        if sim >= threshold:
            # 当前消息与上一条过于相似 → 移除旧的，保留新的
            if len(kept) > 0:
                kept[-1] = messages[i]  # 替换为新的
            removed += 1
            logger.debug(f"[Reducer] 去重: sim={sim:.2f}, text={curr_text[:40]}...")
        else:
            kept.append(messages[i])

    return kept, removed


# ==================== 无关信息检测 ====================

def _check_irrelevant(msg: BaseMessage) -> tuple[bool, str]:
    """检查消息是否为无关信息。"""
    content = _get_message_text(msg).strip()

    # 1) 纯表情/符号
    if not content:
        return True, "empty"
    if len(content) <= 2 and all(
        ch in "。，！？…~～.。!?…—…、~" or '一' > ch or ch > '鿿'
        for ch in content
    ):
        # 纯符号/表情（没有实质文字）
        if not any('一' <= ch <= '鿿' for ch in content):
            return True, "emoji_only"

    # 2) 单字回复
    if len(content) == 1 and '一' <= content <= '鿿':
        return True, "single_char"

    # 3) 重复追问（连续 3 条都是"继续"/"还有吗"等）
    repeated_patterns = ["继续", "还有吗", "再来", "换一批", "更多"]
    if content in repeated_patterns:
        return True, "repeated_continuation"

    return False, ""


# ==================== 摘要生成 ====================

def _generate_trim_summary(
    removed_messages: list[BaseMessage],
    max_chars: int = 200,
) -> str:
    """为被裁剪的消息生成简短摘要。

    采用规则方法（不调用 LLM）：
    - 提取问句
    - 提取实体关键词
    - 合并为摘要文本
    """
    if not removed_messages:
        return ""

    summary_parts: list[str] = []
    total_chars = 0

    for msg in removed_messages:
        text = _get_message_text(msg).strip()
        if not text:
            continue

        # 提取首句或关键片段
        if "?" in text or "？" in text:
            # 有问句→保留完整问句
            snippet = text[:80]
        elif len(text) > 60:
            snippet = text[:60] + "…"
        else:
            snippet = text

        if total_chars + len(snippet) > max_chars:
            remaining = len(removed_messages) - len(summary_parts)
            summary_parts.append(f"（还有 {remaining} 条消息被裁剪）")
            break

        summary_parts.append(snippet)
        total_chars += len(snippet)

    if not summary_parts:
        return ""

    return "## 对话历史摘要（以下为裁剪的旧消息概要）\n" + "\n".join(
        f"- {p}" for p in summary_parts
    )


# ==================== 辅助函数 ====================

def _get_message_text(msg: BaseMessage) -> str:
    """从消息对象中提取文本内容。"""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
        return "".join(parts)
    return ""


def _is_user_message(msg) -> bool:
    if _HAS_LANGCHAIN:
        return isinstance(msg, HumanMessage)
    # Fallback: check by class name
    cls_name = type(msg).__name__
    return cls_name == "HumanMessage"


def _is_ai_message(msg) -> bool:
    if _HAS_LANGCHAIN:
        return isinstance(msg, AIMessage)
    cls_name = type(msg).__name__
    return cls_name == "AIMessage"


# ==================== 上下文裁剪器 ====================

class ContextReducer:
    """语义级上下文裁剪器。

    与 context_trimmer.py 的分工：
    - Reducer 决定**哪些消息重要/可移除**（语义层面）
    - Trimmer 负责**确保不超 token 上限**（数量层面）
    - 两者协同：Reducer 标记 → Trimmer 按预算裁剪

    使用示例::

        reducer = ContextReducer()
        result = reducer.reduce(
            messages=trimmed_history,
            query_entities=analysis.entities,
            max_tokens=2800,
        )
        # result.kept_messages — 裁剪后的消息列表
        # result.trim_summary — 被移除内容的摘要
    """

    def __init__(self):
        self._min_rounds = _REDUCER_CFG.get("min_rounds", 3)
        self._summary_max_chars = _REDUCER_CFG.get("summary_max_chars", 200)
        self._dedup_threshold = _REDUCER_CFG.get("dedup_threshold", 0.75)

    def reduce(
        self,
        messages: Sequence[BaseMessage],
        query_entities: list | None = None,
        max_tokens: int | None = None,
        min_rounds: int | None = None,
    ) -> ReduceResult:
        """对消息历史进行语义级裁剪。

        Args:
            messages: 完整的消息历史列表。
            query_entities: 当前查询中提取的实体（用于重要性评分）。
            max_tokens: 最大 token 数限制。None 则不限制。
            min_rounds: 最少保留轮数。None 则从配置读取。

        Returns:
            ``ReduceResult`` 包含裁剪后的消息和统计信息。
        """
        if not messages:
            return ReduceResult(
                kept_messages=[],
                removed_count=0,
                deduplicated_count=0,
                irrelevant_count=0,
                trim_summary="",
                importance_scores=[],
            )

        min_rounds = min_rounds if min_rounds is not None else self._min_rounds
        messages_list = list(messages)

        # ---- 第 1 步：去重 ----
        deduped, dedup_count = _deduplicate(messages_list)

        # ---- 第 2 步：无关信息标记 ----
        irrelevant_indices: set[int] = set()
        for i, msg in enumerate(deduped):
            is_irr, reason = _check_irrelevant(msg)
            if is_irr:
                irrelevant_indices.add(i)

        # ---- 第 3 步：重要性评分 ----
        scores: list[MessageScore] = []
        for i, msg in enumerate(deduped):
            score = _score_message(msg, i, len(deduped), query_entities)
            if i in irrelevant_indices:
                score.is_irrelevant = True
                _, reason = _check_irrelevant(msg)
                score.irrelevance_reason = reason
                score.total_score *= 0.1  # 无关消息大幅降权
            scores.append(score)

        # ---- 第 4 步：按预算裁剪 ----
        if max_tokens is not None and max_tokens > 0:
            kept, removed_msgs = self._trim_by_budget(
                deduped, scores, max_tokens, min_rounds
            )
        else:
            # 仅移除无关信息
            kept = [
                msg for i, msg in enumerate(deduped)
                if i not in irrelevant_indices
                or len(deduped) - len(irrelevant_indices) < min_rounds * 2
            ]
            removed_msgs = [msg for i, msg in enumerate(deduped) if msg not in kept]

        # 确保最少保留
        if len(kept) < min_rounds * 2:  # 每轮至少2条消息
            kept = deduped[-min_rounds * 2:]

        # ---- 第 5 步：生成摘要 ----
        irrelevant_removed = sum(
            1 for i in irrelevant_indices
            if deduped[i] in removed_msgs
        )
        trim_summary = _generate_trim_summary(removed_msgs, self._summary_max_chars)

        logger.info(
            f"[Reducer] 裁剪完成: {len(messages_list)} → {len(kept)} 条消息 "
            f"(去重={dedup_count}, 无关={irrelevant_removed}, 预算={len(removed_msgs) - dedup_count - irrelevant_removed})"
        )

        return ReduceResult(
            kept_messages=kept,
            removed_count=len(removed_msgs),
            deduplicated_count=dedup_count,
            irrelevant_count=irrelevant_removed,
            trim_summary=trim_summary,
            importance_scores=scores,
        )

    def _trim_by_budget(
        self,
        messages: list[BaseMessage],
        scores: list[MessageScore],
        max_tokens: int,
        min_rounds: int,
    ) -> tuple[list[BaseMessage], list[BaseMessage]]:
        """按 token 预算裁剪，优先保留高重要性消息。"""
        from agent.cita.budget import estimate_tokens

        # 从后往前累计 token
        total = 0
        kept_indices: set[int] = set()

        # 倒序遍历（优先保留最新消息）
        for i in range(len(messages) - 1, -1, -1):
            msg_tokens = estimate_tokens(scores[i].content)
            if total + msg_tokens <= max_tokens:
                total += msg_tokens
                kept_indices.add(i)
            else:
                break

        # 确保最少保留
        min_msgs = min_rounds * 2
        if len(kept_indices) < min_msgs:
            # 强制保留最后 N 条
            for i in range(max(0, len(messages) - min_msgs), len(messages)):
                kept_indices.add(i)

        kept = [msg for i, msg in enumerate(messages) if i in kept_indices]
        removed = [msg for i, msg in enumerate(messages) if i not in kept_indices]

        return kept, removed

    # ==================== 辅助：轮次分组 ====================

    @staticmethod
    def group_into_rounds(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
        """将消息列表按对话轮次分组（与 context_trimmer 保持一致）。

        每条 HumanMessage 开启新的一轮。
        """
        rounds: list[list[BaseMessage]] = []
        current_round: list[BaseMessage] = []

        for msg in messages:
            if isinstance(msg, HumanMessage) and current_round:
                rounds.append(current_round)
                current_round = [msg]
            else:
                current_round.append(msg)

        if current_round:
            rounds.append(current_round)

        return rounds


# ==================== 便捷函数 ====================

def reduce_context(
    messages: Sequence[BaseMessage],
    query: str = "",
    query_entities: list | None = None,
    max_tokens: int | None = None,
) -> ReduceResult:
    """快速裁剪上下文的便捷函数。

    Args:
        messages: 消息历史。
        query: 当前查询文本（可选，用于实体提取）。
        query_entities: 预提取的实体列表。
        max_tokens: token 上限。

    Returns:
        ReduceResult。
    """
    reducer = ContextReducer()

    # 如果提供了 query 但没有实体，自动提取
    if query and not query_entities:
        try:
            from agent.cita.semantic import semantic_engine
            analysis = semantic_engine.analyze(query)
            query_entities = analysis.entities
        except Exception:
            pass

    return reducer.reduce(
        messages=messages,
        query_entities=query_entities,
        max_tokens=max_tokens,
    )


# ==================== 测试 ====================

if __name__ == "__main__":
    from langchain_core.messages import HumanMessage, AIMessage

    messages = [
        HumanMessage(content="你好！"),
        AIMessage(content="你好呀！有什么可以帮你的吗？"),
        HumanMessage(content="我想找一些好看的动漫"),
        AIMessage(content="好的，你想看什么类型的呢？"),
        HumanMessage(content="热血番吧，像《鬼灭之刃》那种"),
        AIMessage(content="推荐《咒术回战》《炎炎消防队》..."),
        HumanMessage(content="谢谢！"),
        AIMessage(content="不客气！还有其他需要吗？"),
        HumanMessage(content="嗯嗯"),
        AIMessage(content="好的，随时找我哦~"),
        HumanMessage(content="继续"),
        AIMessage(content="好的，再推荐几部..."),
        HumanMessage(content="还有吗？"),
        AIMessage(content="《进击的巨人》《钢之炼金术师》..."),
        HumanMessage(content="换一批"),
        AIMessage(content="《死神》《海贼王》《龙珠》..."),
    ]

    # 模拟实体
    from agent.cita.semantic import Entity
    entities = [Entity(type="anime", value="鬼灭之刃", confidence=0.95)]

    reducer = ContextReducer()
    result = reducer.reduce(
        messages=messages,
        query_entities=entities,
        max_tokens=500,
    )

    print(f"原始: {len(messages)} 条")
    print(f"保留: {len(result.kept_messages)} 条")
    print(f"去重: {result.deduplicated_count} 条")
    print(f"无关: {result.irrelevant_count} 条")
    print(f"\n--- 保留的消息 ---")
    for msg in result.kept_messages:
        role = "U" if isinstance(msg, HumanMessage) else "A"
        print(f"[{role}] {_get_message_text(msg)[:60]}")

    if result.trim_summary:
        print(f"\n--- 裁剪摘要 ---\n{result.trim_summary}")

    print(f"\n--- 重要性评分 ---")
    for s in result.importance_scores:
        marker = "✗" if s.is_irrelevant else ("Δ" if s.is_duplicate else "✓")
        print(f"  {marker} [{s.index}] score={s.total_score:.2f} "
              f"entity={s.has_entity} q={s.has_question} "
              f"emo={s.has_emotion} recent={s.is_recent} "
              f"len={s.length_factor:.1f} | {s.content[:40]}")
