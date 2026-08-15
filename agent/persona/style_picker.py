"""
风格选择器
==========
按场景、用户情绪、话题自动选择最佳语气风格。

选择策略（优先级从高到低）：
1. **手动指定**：用户在 UI 中选择的风格 → 直接使用
2. **情绪映射**：检测到用户强烈情绪 → 按映射表选择
3. **话题映射**：检测到特定话题 → 按映射表选择
4. **角色默认**：角色的最佳风格列表中的第一个
5. **全局默认**："default"

使用方式::

    from agent.persona.style_picker import StylePicker

    picker = StylePicker()
    selection = picker.pick(
        user_emotions=["sad"],
        topic="emotional_support",
        persona="Cyrene",
    )
    # selection.style → "healing"
    # selection.reason → "用户情绪悲伤 → 推荐治愈风格"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from utils.logger_handler import logger

# 配置加载
def _load_persona_cfg() -> dict:
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/persona.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except Exception:
        return {}

_PERSONA_CFG = _load_persona_cfg()
_EMOTION_STYLE_MAP: dict = _PERSONA_CFG.get("emotion_style_map", {})
_TOPIC_STYLE_MAP: dict = _PERSONA_CFG.get("topic_style_map", {})
_CHAR_CFG: dict = _PERSONA_CFG.get("characters", {})
_STYLES_CFG: dict = _PERSONA_CFG.get("styles", {})


# ==================== 数据结构 ====================

@dataclass
class StyleSelection:
    """风格选择结果。"""
    style: str                              # 选中的风格名
    confidence: float                       # 置信度 0.0 ~ 1.0
    reason: str                             # 选择理由
    source: str = "default"                 # 来源: manual / emotion / topic / character / default
    alternative: str = ""                   # 备选风格
    temperature: float = 0.5                # 建议温度参数
    verbosity: float = 0.5                  # 建议详细度


# ==================== 风格选择器 ====================

class StylePicker:
    """场景/情绪感知的自动风格选择器。

    决策流程::

        用户输入
            │
            ▼
        ┌─────────────┐
        │ 1. 手动指定? │──是──→ 直接使用
        └──────┬──────┘
              │ 否
              ▼
        ┌─────────────┐
        │ 2. 情绪映射? │──是──→ 按情绪选风格
        └──────┬──────┘
              │ 否
              ▼
        ┌─────────────┐
        │ 3. 话题映射? │──是──→ 按话题选风格
        └──────┬──────┘
              │ 否
              ▼
        ┌─────────────┐
        │ 4. 角色默认  │──→ 角色的最佳风格
        └─────────────┘

    使用示例::

        picker = StylePicker()
        sel = picker.pick(
            user_emotions=["sad"],
            topic="emotional_support",
            persona="Cyrene",
        )
        print(f"Selected: {sel.style} — {sel.reason}")
    """

    # 可用风格列表
    AVAILABLE_STYLES = list(_STYLES_CFG.keys()) if _STYLES_CFG else [
        "default", "lively", "healing", "focused", "sweet",
    ]

    # 旧风格名 → 新风格名兼容映射（serious 已更名为 focused）
    _STYLE_ALIASES: dict[str, str] = {
        "serious": "focused",
    }

    def _normalize(self, style: str | None) -> str | None:
        """将旧风格名映射到新风格名。"""
        if style:
            return self._STYLE_ALIASES.get(style, style)
        return style

    def pick(
        self,
        persona: str | None = None,
        user_emotions: list[str] | None = None,
        topic: str | None = None,
        manual_style: str | None = None,
        conversation_stage: str | None = None,
        time_of_day: str | None = None,
    ) -> StyleSelection:
        """根据上下文自动选择最佳语气风格。

        Args:
            persona: 当前角色名。
            user_emotions: 用户情绪列表（从 CITA SemanticEngine 获取）。
            topic: 检测到的话题标签。
            manual_style: 用户手动选择的风格（最高优先级）。
            conversation_stage: 对话阶段（greeting / deep_talk / farewell）。
            time_of_day: 时间段（morning / afternoon / evening / night）。

        Returns:
            StyleSelection 包含选中的风格及理由。
        """
        # ---- Level 1: 手动指定 ----
        manual_style = self._normalize(manual_style)
        if manual_style and manual_style in self.AVAILABLE_STYLES:
            return self._make_selection(
                manual_style, 1.0, f"用户手动选择: {manual_style}", "manual"
            )

        # ---- Level 2: 情绪映射 ----
        if user_emotions:
            emotion_sel = self._pick_by_emotion(user_emotions, persona)
            if emotion_sel:
                return emotion_sel

        # ---- Level 3: 话题映射 ----
        if topic:
            topic_sel = self._pick_by_topic(topic, persona)
            if topic_sel:
                return topic_sel

        # ---- Level 4: 时间段调整 ----
        if time_of_day == "night" and "healing" in self.AVAILABLE_STYLES:
            return self._make_selection(
                "healing", 0.4,
                "深夜时段 → 推荐治愈风格",
                "time"
            )

        # ---- Level 5: 角色默认 ----
        if persona:
            char_cfg = _CHAR_CFG.get(persona, {})
            best_styles = char_cfg.get("best_styles", ["default"])
            if best_styles:
                style = best_styles[0]
                if style in self.AVAILABLE_STYLES:
                    return self._make_selection(
                        style, 0.3,
                        f"角色 {persona} 的默认风格: {style}",
                        "character"
                    )

        # ---- Level 6: 全局默认 ----
        return self._make_selection(
            "default", 0.1,
            "全局默认风格",
            "default"
        )

    def _pick_by_emotion(
        self, emotions: list[str], persona: str | None
    ) -> StyleSelection | None:
        """根据用户情绪选择风格。"""
        # 取最强的情绪
        primary_emotion = emotions[0] if emotions else None
        if not primary_emotion:
            return None

        mapping = _EMOTION_STYLE_MAP.get(primary_emotion)
        if not mapping:
            return None

        style = self._normalize(mapping.get("primary", "default"))
        reason = mapping.get("reason", f"用户情绪 {primary_emotion}")

        # 检查角色的最佳风格中是否包含映射风格
        if persona:
            char_cfg = _CHAR_CFG.get(persona, {})
            best_styles = char_cfg.get("best_styles", ["default"])
            if style not in best_styles:
                # 角色不支持此风格 → 使用 secondary 或在 best_styles 中选
                secondary = mapping.get("secondary", "default")
                if secondary in best_styles:
                    style = secondary
                else:
                    style = best_styles[0]

        return self._make_selection(style, 0.7, reason, "emotion")

    def _pick_by_topic(
        self, topic: str, persona: str | None
    ) -> StyleSelection | None:
        """根据话题选择风格。"""
        mapping = _TOPIC_STYLE_MAP.get(topic)
        if not mapping:
            return None

        style = self._normalize(mapping.get("primary", "default"))
        reason = mapping.get("reason", f"话题 {topic}")

        # 检查角色兼容性
        if persona:
            char_cfg = _CHAR_CFG.get(persona, {})
            best_styles = char_cfg.get("best_styles", ["default"])
            if style not in best_styles:
                style = best_styles[0]
                reason += f"（调整为角色支持的 {style}）"

        return self._make_selection(style, 0.6, reason, "topic")

    def _make_selection(
        self, style: str, confidence: float, reason: str, source: str
    ) -> StyleSelection:
        """构建 StyleSelection 对象。"""
        style_cfg = _STYLES_CFG.get(style, {})
        return StyleSelection(
            style=style,
            confidence=confidence,
            reason=reason,
            source=source,
            alternative="",
            temperature=style_cfg.get("temperature", 0.5),
            verbosity=style_cfg.get("verbosity", 0.5),
        )

    # ==================== 角色推荐 ====================

    def recommend_character(
        self, emotions: list[str] | None = None
    ) -> list[str]:
        """根据用户情绪推荐合适的角色。

        Args:
            emotions: 用户情绪列表。

        Returns:
            推荐的角色名列表（按推荐度降序）。
        """
        if not emotions:
            return ["Cyrene"]  # 默认推荐

        primary = emotions[0]
        emotion_map = _PERSONA_CFG.get("emotion_character_map", {})
        mapping = emotion_map.get(primary, {})
        return mapping.get("recommend", ["Cyrene"])

    def recommend_character_with_reason(
        self, emotions: list[str] | None = None
    ) -> tuple[list[str], str]:
        """推荐角色并附上理由。"""
        if not emotions:
            return ["Cyrene"], "无特殊情绪，推荐默认角色 Cyrene"

        primary = emotions[0]
        emotion_map = _PERSONA_CFG.get("emotion_character_map", {})
        mapping = emotion_map.get(primary, {})
        chars = mapping.get("recommend", ["Cyrene"])
        reason = mapping.get("reason", "")

        return chars, reason

    @classmethod
    def list_styles(cls) -> list[dict]:
        """列出所有可用风格及描述。"""
        return [
            {
                "name": name,
                "display_name": cfg.get("display_name", name),
                "description": cfg.get("description", ""),
                "temperature": cfg.get("temperature", 0.5),
            }
            for name, cfg in _STYLES_CFG.items()
        ]


# ==================== 模块级实例 ====================

style_picker = StylePicker()


# ==================== 测试 ====================

if __name__ == "__main__":
    picker = StylePicker()

    test_cases = [
        (["sad"], "emotional_support", "Cyrene", None),
        (["happy"], "anime_recommend", "Cyrene", None),
        (["angry"], None, "Columbina", None),
        (["confused"], "tech_support", "Zhuang Fangyi", None),
        ([], "casual_chat", "Ye Shunguang", None),
        (["urgent"], None, "Zhuang Fangyi", None),
        ([], None, "Cyrene", "lively"),  # manual
    ]

    for emotions, topic, persona, manual in test_cases:
        sel = picker.pick(
            user_emotions=emotions,
            topic=topic,
            persona=persona,
            manual_style=manual,
        )
        print(
            f"[{sel.source:10s}] style={sel.style:8s} "
            f"conf={sel.confidence:.1f} | "
            f"emotions={emotions!s:20s} topic={topic!s:15s} persona={persona} "
            f"→ {sel.reason}"
        )

    print(f"\n可用风格: {picker.list_styles()}")
    print(f"推荐角色 (sad): {picker.recommend_character(['sad'])}")
    print(f"推荐角色 (happy): {picker.recommend_character(['happy'])}")
