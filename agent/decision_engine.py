"""
Decision Engine — 快/慢路由
===========================
在 Agent 执行前判断用户消息是否需要工具调用，将纯闲聊路由到
轻量 Chat 路径，节省 Token 和延迟。

架构
----
三层决策 + 一层缓存::

    用户消息
        │
        ▼
    ┌──────────────┐
    │ 1. 规则层     │ ← 关键词匹配，覆盖 ~85%，0ms
    │    (Rule)     │
    └──────┬───────┘
           │ 不确定？
           ▼
    ┌──────────────┐
    │ 2. CITA 层   │ ← 复用现有意图分类，0ms
    │    (CITA)     │
    └──────┬───────┘
           │ 不确定？
           ▼
    ┌──────────────┐
    │ 3. LLM 层    │ ← 快模型二分类，~300ms（可选）
    │    (LLM)      │
    └──────┬───────┘
           │
           ▼
    ┌──────────────┐
    │ 4. 缓存层     │ ← 同话题跳过重复判断
    │    (Cache)    │
    └──────────────┘

使用方式::

    from agent.decision_engine import decision_engine, Decision

    result = decision_engine.evaluate("你好")
    # Decision(route="chat", confidence=0.95, reason="greeting")

    result = decision_engine.evaluate("推荐几部热血番")
    # Decision(route="agent", confidence=0.95, reason="anime_keyword")
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

from utils.config_handler import decision_config
from utils.logger_handler import logger

# ==================== 配置 ====================

_CFG = decision_config
_AGENT_TRIGGERS: dict[str, list[str]] = _CFG.get("agent_triggers", {})
_CHAT_SIGNALS: dict[str, list[str]] = _CFG.get("chat_signals", {})
_SKILL_NAMESPACES: list[str] = _CFG.get("skill_namespaces", [])
_AGENT_CONTINUATIONS: list[str] = _CFG.get("agent_continuations", [])
_TOPIC_CHANGE_SIGNALS: list[str] = _CFG.get("cache", {}).get("topic_change_signals", [])

# 所有 agent 触发关键词（扁平化）
_ALL_AGENT_KEYWORDS: list[str] = []
for _category, _kws in _AGENT_TRIGGERS.items():
    _ALL_AGENT_KEYWORDS.extend(_kws)

# 所有 chat 信号关键词（扁平化）
_ALL_CHAT_KEYWORDS: list[str] = []
for _category, _kws in _CHAT_SIGNALS.items():
    _ALL_CHAT_KEYWORDS.extend(_kws)


# ==================== 数据结构 ====================

@dataclass
class Decision:
    """决策结果。

    Attributes:
        route: 路由目标 — ``"chat"`` 或 ``"agent"``。
        confidence: 置信度 0.0 ~ 1.0。
        reason: 决策依据（用于日志和调试）。
        source: 决策来源 — ``"rule"`` / ``"cita"`` / ``"llm"`` / ``"cache"``。
    """
    route: str          # "chat" | "agent"
    confidence: float
    reason: str
    source: str = "rule"

    @property
    def is_chat(self) -> bool:
        return self.route == "chat"

    @property
    def is_agent(self) -> bool:
        return self.route == "agent"


# ==================== 缓存 ====================

@dataclass
class _CacheEntry:
    route: str
    last_topic: str
    chat_streak: int = 0
    timestamp: float = field(default_factory=time.time)


# ==================== 引擎 ====================

class DecisionEngine:
    """快/慢路由决策引擎。

    每轮对话开始时调用 ``evaluate()`` 判断走 Chat 还是 Agent 路径。
    """

    def __init__(self):
        self._cache: dict[str, _CacheEntry] = {}  # session_id → entry
        self._stats: dict[str, dict[str, int]] = {}  # session_id → {chat: N, agent: M}
        self._ttl = _CFG.get("cache", {}).get("ttl_seconds", 300)
        self._streak_threshold = _CFG.get("cache", {}).get("chat_streak_threshold", 2)
        self._llm_enabled = _CFG.get("llm_layer", {}).get("enabled", True)
        self._llm_min_confidence = _CFG.get("llm_layer", {}).get("min_rule_confidence", 0.6)

    @staticmethod
    def _has_explicit_tool_hint(query_lower: str) -> bool:
        """识别必须使用外部数据的表达，避免聊天缓存绕过工具。"""
        tool_hints = (
            "联网", "网上查", "查一下", "查找", "搜索", "查询", "最新",
            "实时", "今天", "当前", "现在", "公告", "资讯", "活动",
            "最新章节", "作者", "原神", "崩坏", "星穹铁道", "绝区零",
            "米游社", "起点", "小说",
        )
        return any(hint in query_lower for hint in tool_hints)

    # ==================== 主入口 ====================

    def evaluate(
        self,
        query: str,
        session_id: str = "default",
        history: list | None = None,
        _llm_classifier=None,  # 依赖注入，测试用
    ) -> Decision:
        """评估用户消息，返回路由决策。

        Args:
            query: 用户输入文本。
            session_id: 会话标识（用于缓存）。
            history: 历史消息列表（用于上下文判断）。
            _llm_classifier: LLM 分类函数（依赖注入，测试时用）。

        Returns:
            ``Decision`` 对象。
        """
        if not query or not query.strip():
            return Decision(route="chat", confidence=1.0, reason="empty_query", source="rule")

        query_lower = query.lower().strip()

        # 明确要求实时/外部资料时，禁止复用 chat 路由缓存。
        if self._has_explicit_tool_hint(query_lower):
            forced = Decision(route="agent", confidence=0.95, reason="explicit_tool_hint", source="rule")
            self._update_stats(session_id, "agent")
            self._update_cache(session_id, "agent", query_lower)
            return forced

        cache_entry = self._get_cache(session_id)

        # ---- 话题切换检测 ----
        if cache_entry and self._is_topic_change(query_lower):
            logger.debug(f"[Decision] 话题切换，清除缓存: {query[:30]}")
            self._clear_cache(session_id)
            cache_entry = None

        # ---- Layer 4: 缓存命中 ----
        if cache_entry and cache_entry.chat_streak >= self._streak_threshold:
            # 连续 N 条 chat，但要检查是否为 agent 触发或追问
            has_agent = self._has_agent_keyword(query_lower)
            is_cont = self._is_continuation(query_lower, history)
            if not has_agent and not is_cont:
                cache_entry.chat_streak += 1
                cache_entry.timestamp = time.time()
                logger.info(f"[Decision] 缓存命中 → chat (streak={cache_entry.chat_streak})")
                return Decision(route="chat", confidence=0.7, reason=f"cache_streak", source="cache")
            else:
                # 有 agent 关键词或追问 → 打破聊天连续，重置缓存
                logger.info(f"[Decision] 缓存打破 streak: agent={bool(has_agent)} cont={is_cont}")
                self._clear_cache(session_id)
                cache_entry = None

        # ---- Layer 1: 规则层 ----
        result = self._rule_evaluate(query_lower)
        if result and result.confidence >= 0.85:
            self._update_stats(session_id, result.route)
            self._update_cache(session_id, result.route, query_lower)
            return result

        # ---- Layer 1b: CITA 层 ----
        cita_result = self._cita_evaluate(query_lower)
        if cita_result:
            # 合并规则层和 CITA 层结果
            merged = self._merge_results(result, cita_result)
            if merged.confidence >= 0.7:
                self._update_stats(session_id, merged.route)
                self._update_cache(session_id, merged.route, query_lower)
                return merged

        # ---- Layer 2: 规则 + 追问检测 ----
        if cache_entry and cache_entry.route == "agent":
            if self._is_continuation(query_lower, history):
                self._update_stats(session_id, "agent")
                self._update_cache(session_id, "agent", query_lower)
                logger.info(f"[Decision] 追问继续 → agent")
                return Decision(route="agent", confidence=0.8, reason="continuation_in_agent", source="rule")

        # ---- Layer 3: LLM 层（可选） ----
        if self._llm_enabled and _llm_classifier is not None:
            try:
                llm_route = _llm_classifier(query)
                if llm_route in ("chat", "agent"):
                    logger.info(f"[Decision] LLM → {llm_route}")
                    decision = Decision(route=llm_route, confidence=0.75, reason="llm_classifier", source="llm")
                    self._update_stats(session_id, llm_route)
                    self._update_cache(session_id, llm_route, query_lower)
                    return decision
            except Exception as e:
                logger.warning(f"[Decision] LLM 分类失败: {e}")

        # ---- Fallback: 默认走 Agent（宁可多加载工具，不可功能缺失） ----
        default = Decision(route="agent", confidence=0.3, reason="fallback_default", source="rule")
        self._update_stats(session_id, "agent")
        self._update_cache(session_id, "agent", query_lower)
        return default

    # ==================== 规则层 ====================

    def _rule_evaluate(self, query_lower: str) -> Decision | None:
        """关键词规则匹配。

        Returns:
            Decision 如果明确匹配，None 如果不确定。
        """
        # 1) 检查 agent 触发词（高优先级）
        agent_match = self._has_agent_keyword(query_lower)
        # 2) 检查 chat 信号
        chat_signal = self._detect_chat_signal(query_lower)

        if agent_match and not chat_signal:
            return Decision(route="agent", confidence=0.95, reason=f"agent_keyword:{agent_match}", source="rule")

        if chat_signal and not agent_match:
            return Decision(route="chat", confidence=0.95, reason=f"chat_signal:{chat_signal}", source="rule")

        if agent_match and chat_signal:
            # 冲突：短消息（< 8 字符）的社交信号优先
            # "谢谢推荐" = 感恩 > agent 词；"推荐几部好看的" = 任务 > 社交
            if len(query_lower) <= 8:
                return Decision(route="chat", confidence=0.7,
                                reason=f"conflict_short_chat:{chat_signal}>{agent_match}", source="rule")
            # 长消息：agent 触发词优先（宁可多加载，不缺失功能）
            return Decision(route="agent", confidence=0.6, reason=f"conflict_agent_priority:{agent_match}", source="rule")

        # 不确定
        return None

    def _has_agent_keyword(self, query_lower: str) -> str:
        """检查是否包含 agent 触发关键词。返回匹配的类别名，否则空字符串。"""
        for category, keywords in _AGENT_TRIGGERS.items():
            for kw in keywords:
                if kw in query_lower:
                    return category

        # 检查 Skill 命名空间
        for ns in _SKILL_NAMESPACES:
            if ns in query_lower:
                return "skill"

        return ""

    def _detect_chat_signal(self, query_lower: str) -> str:
        """检查是否包含明确的闲聊信号。返回匹配的类别名，否则空字符串。"""
        for category, signals in _CHAT_SIGNALS.items():
            for signal in signals:
                if signal in query_lower:
                    return category
        return ""

    # ==================== CITA 层 ====================

    def _cita_evaluate(self, query_lower: str) -> Decision | None:
        """复用 CITA 分类结果。"""
        try:
            from agent.cita_classifier import classify_intent
            result = classify_intent(query_lower)
            if result.intent_type == "chitchat" and result.confidence >= 0.5:
                return Decision(route="chat", confidence=result.confidence,
                                reason="cita_chitchat", source="cita")
            if result.intent_type == "report":
                return Decision(route="agent", confidence=0.9,
                                reason="cita_report", source="cita")
            if result.needs_web_search or result.needs_rag:
                return Decision(route="agent", confidence=0.8,
                                reason="cita_needs_tool", source="cita")
        except Exception as e:
            logger.warning(f"[Decision] CITA 分类异常: {e}")
        return None

    # ==================== 合并逻辑 ====================

    def _merge_results(self, rule: Decision | None, cita: Decision | None) -> Decision:
        """合并规则层和 CITA 层的结果。"""
        if rule and cita:
            if rule.route == cita.route:
                return Decision(route=rule.route, confidence=max(rule.confidence, cita.confidence),
                                reason=f"merged:{rule.reason}+{cita.reason}", source="merged")
            # 冲突：agent 优先
            return Decision(route="agent", confidence=0.5,
                            reason=f"conflict:cita={cita.route},rule={rule.route}", source="merged")
        return rule or cita or Decision(route="agent", confidence=0.3, reason="unknown", source="rule")

    # ==================== 追问检测 ====================

    def _is_continuation(self, query_lower: str, history: list | None) -> bool:
        """检测是否为 Agent 上下文的追问/继续指令。"""
        for cont in _AGENT_CONTINUATIONS:
            if cont in query_lower:
                return True

        # 短消息 + 前一条是 agent 回复 → 可能是追问
        if len(query_lower) <= 5 and history:
            return True

        return False

    def _is_topic_change(self, query_lower: str) -> bool:
        """检测是否为话题切换。"""
        for signal in _TOPIC_CHANGE_SIGNALS:
            if signal in query_lower:
                return True
        return False

    # ==================== 缓存管理 ====================

    def _get_cache(self, session_id: str) -> _CacheEntry | None:
        """获取会话缓存（检查 TTL）。"""
        entry = self._cache.get(session_id)
        if entry and (time.time() - entry.timestamp) > self._ttl:
            del self._cache[session_id]
            return None
        return entry

    def _update_cache(self, session_id: str, route: str, query: str):
        """更新缓存条目。"""
        existing = self._cache.get(session_id)
        if existing and existing.route == route:
            existing.chat_streak += 1
        else:
            existing = _CacheEntry(route=route, last_topic=query[:50])
        existing.timestamp = time.time()
        self._cache[session_id] = existing

    def _clear_cache(self, session_id: str):
        """清除指定会话的缓存。"""
        self._cache.pop(session_id, None)

    # ==================== 统计 ====================

    def _update_stats(self, session_id: str, route: str):
        """更新路由统计。"""
        if session_id not in self._stats:
            self._stats[session_id] = {"chat": 0, "agent": 0}
        self._stats[session_id][route] += 1

    def get_stats(self, session_id: str) -> dict:
        """获取指定会话的路由统计。

        Returns:
            ``{"chat": N, "agent": M, "chat_ratio": 0.XX}``
        """
        stats = self._stats.get(session_id, {"chat": 0, "agent": 0})
        total = stats["chat"] + stats["agent"]
        ratio = stats["chat"] / total if total > 0 else 0
        return {
            "chat": stats["chat"],
            "agent": stats["agent"],
            "total": total,
            "chat_ratio": round(ratio, 3),
        }

    def clear_session(self, session_id: str):
        """清除会话的缓存和统计。"""
        self._cache.pop(session_id, None)
        self._stats.pop(session_id, None)


# ==================== 模块级单例 ====================

decision_engine = DecisionEngine()


# ==================== 便捷函数 ====================

async def llm_classify(query: str) -> str:
    """使用 LLM 进行 chat/agent 二分类。

    使用与主 Agent 相同的模型，但 prompt 极简（约 50 token），
    比完整 ReAct 循环便宜 10-50 倍。

    Args:
        query: 用户输入文本。

    Returns:
        ``"chat"`` 或 ``"agent"``。
    """
    try:
        from model.factory import chat_model
        prompt = _CFG.get("llm_layer", {}).get("prompt",
            "判断以下用户消息是否需要调用工具（搜索、天气、文件、推荐等）。"
            "仅回答 chat 或 agent。\n\n"
        )
        response = await chat_model.ainvoke(prompt + f"用户消息：{query}")
        text = response.content if hasattr(response, "content") else str(response)
        text = text.strip().lower()
        if "agent" in text:
            return "agent"
        return "chat"
    except Exception as e:
        logger.warning(f"[Decision] LLM 分类异常: {e}")
        return "agent"  # 失败时安全降级


# ==================== 测试 ====================

if __name__ == "__main__":
    engine = DecisionEngine()

    test_cases = [
        ("你好", "chat"),
        ("嗨，在吗", "chat"),
        ("谢谢你的帮助", "chat"),
        ("我今天心情不好", "chat"),
        ("推荐几部热血番", "agent"),
        ("今天天气怎么样", "agent"),
        ("帮我搜一下最新的动漫新闻", "agent"),
        ("下载无职转生小说", "agent"),
        ("再见", "chat"),
        ("你觉得进击的巨人怎么样", "agent"),
        ("你真好", "chat"),
        ("帮我导出报告", "agent"),
        ("嗯嗯", "chat"),
        ("还有类似的推荐吗", "agent"),
    ]

    for query, expected in test_cases:
        result = engine.evaluate(query, session_id="test")
        status = "✅" if result.route == expected else "❌"
        print(f"{status} [{expected:5}] ← {query:30} | {result.route:5} conf={result.confidence:.2f} reason={result.reason}")

    print(f"\n统计: {engine.get_stats('test')}")
