"""
CITA 意图分类器（V1 兼容层）
===========================
本模块所有逻辑已迁移至 ``agent.cita`` 包。

保留此文件作为 V1 兼容入口——原有所有 ``from agent.cita_classifier import ...``
语句无需修改，内部自动路由到 CITA 2.0 语义引擎。

V1 → V2 映射
-------------
- ``classify_intent()`` → ``agent.cita.semantic.classify_intent()``
- ``build_cita_overlay()`` → ``agent.cita.semantic.build_cita_overlay()``（兼容 V1 IntentResult）
- ``IntentResult`` → ``agent.cita.SemanticAnalysis``（别名兼容）

使用方式（不变）::

    from agent.cita_classifier import classify_intent, build_cita_overlay, IntentResult

    result = classify_intent("我的项目启动失败了怎么办")
    # result.intent_type, result.emotions, result.needs_rag, ...
    overlay = build_cita_overlay(result)
"""

from agent.cita.semantic import (
    classify_intent,
    build_cita_overlay,
    SemanticAnalysis,
    EmotionSignal,
    IntentLabel,
)

# V1 兼容别名
IntentResult = SemanticAnalysis

__all__ = [
    "classify_intent",
    "build_cita_overlay",
    "IntentResult",
    "SemanticAnalysis",
    "EmotionSignal",
    "IntentLabel",
]
