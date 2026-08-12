"""
Persona 角色引擎（Phase 4）
==========================
从 "Prompt 覆盖" 升级为完整的 "角色引擎"，支持：
- 角色灵魂加载 + 缓存 + 热重载
- 场景/情绪感知的自动风格选择
- 智能世界观知识检索（按需注入，不浪费 Token）
- 动态语气指令生成（情绪自适应）

模块
----
- ``soul_loader.py``       — 角色灵魂加载 + 缓存 + 热重载
- ``style_picker.py``      — 场景/情绪感知的自动风格选择
- ``worldbook_retriever.py`` — 关键词匹配的世界观知识检索
- ``tone_injector.py``     — 动态语气指令生成
- ``engine.py``            — Persona Engine 主控制器

使用示例::

    from agent.persona import PersonaEngine

    engine = PersonaEngine()
    result = engine.process(
        persona="Cyrene",
        user_emotions=["sad"],
        topic="emotional_support",
        user_query="我今天心情不太好",
    )
    # result.prompt — 组装好的角色提示词
    # result.style — 自动选择的风格
    # result.tone_modifiers — 语气修改指令
"""

from agent.persona.engine import PersonaEngine, PersonaResult
from agent.persona.soul_loader import SoulLoader, SoulMetadata
from agent.persona.style_picker import StylePicker, StyleSelection
from agent.persona.worldbook_retriever import WorldbookRetriever, WorldbookEntry
from agent.persona.tone_injector import ToneInjector, ToneModifier

__all__ = [
    # Engine
    "PersonaEngine", "PersonaResult",
    # Soul
    "SoulLoader", "SoulMetadata",
    # Style
    "StylePicker", "StyleSelection",
    # Worldbook
    "WorldbookRetriever", "WorldbookEntry",
    # Tone
    "ToneInjector", "ToneModifier",
]
