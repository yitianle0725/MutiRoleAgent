"""
CITA 2.0 上下文管理包
=====================
Context / Intent / Token / Allocation

三层架构：Semantic Engine → Reducer → Budget

模块
----
- ``semantic.py`` — 语义引擎：实体提取 + 情绪检测 + 意图分类
- ``reducer.py``  — 结构裁剪器：去重 + 无关移除 + 摘要
- ``budget.py``   — Token 预算：分配 + 追踪 + 超限告警

V1 兼容
-------
原有 ``agent.cita_classifier`` 的 import 路径全部保持可用：
- ``classify_intent()`` → 返回 SemanticAnalysis（兼容 IntentResult 属性访问）
- ``build_cita_overlay()`` → 接受 V1 IntentResult 或 V2 SemanticAnalysis
- ``IntentResult`` → 别名指向 SemanticAnalysis

使用示例::

    # V2 完整流程
    from agent.cita import SemanticEngine, TokenBudget, ContextReducer

    engine = SemanticEngine()
    analysis = engine.analyze("推荐几部热血番")

    budget = TokenBudget(total_budget=8000)
    budget.track("system_prompt", 1500)

    reducer = ContextReducer()
    result = reducer.reduce(messages, analysis.entities, max_tokens=2800)

    # V1 兼容（无需改动现有代码）
    from agent.cita_classifier import classify_intent, build_cita_overlay
    # 内部自动路由到 V2 引擎
"""

# ---- Semantics ----
from agent.cita.semantic import (
    SemanticEngine,
    SemanticAnalysis,
    Entity,
    EmotionSignal,
    IntentLabel,
    EntityExtractor,
    EmotionDetector,
    IntentClassifier,
    RelevanceScorer,
    semantic_engine,
    classify_intent,
    build_cita_overlay,
)

# ---- Reducer ----
from agent.cita.reducer import (
    ContextReducer,
    ReduceResult,
    MessageScore,
    reduce_context,
)

# ---- Budget ----
from agent.cita.budget import (
    TokenBudget,
    BudgetStatus,
    BudgetSnapshot,
    LayerBudget,
    estimate_tokens,
    estimate_messages_tokens,
    create_budget,
)

# V1 兼容别名
# IntentResult 的旧属性 (.intent_type, .emotions, .needs_rag, .needs_web_search, .confidence)
# 均可在 SemanticAnalysis 上访问
IntentResult = SemanticAnalysis  # V1 → V2 兼容

__all__ = [
    # Semantic
    "SemanticEngine", "SemanticAnalysis", "Entity", "EmotionSignal",
    "IntentLabel", "EntityExtractor", "EmotionDetector", "IntentClassifier",
    "RelevanceScorer", "semantic_engine",
    "classify_intent", "build_cita_overlay",
    # Reducer
    "ContextReducer", "ReduceResult", "MessageScore", "reduce_context",
    # Budget
    "TokenBudget", "BudgetStatus", "BudgetSnapshot", "LayerBudget",
    "estimate_tokens", "estimate_messages_tokens", "create_budget",
    # V1 compat
    "IntentResult",
]
