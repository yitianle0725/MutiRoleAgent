"""
语气注入器
==========
按角色灵魂 + 语气风格 + 用户情绪 + 对话阶段，动态生成语气指令。

这是 Persona Engine 的"最后一道工序"——将所有上下文信息转化为
具体的行为指令，注入到 System Prompt 中。

语气指令层级::

    基础语气 (style)
        │
        ├── 情绪修正 (emotion modifier)
        │       └── 用户愤怒 → 额外降低语速、更柔和
        │
        ├── 阶段提示 (stage hint)
        │       └── 开场 → 用角色标志性问候
        │
        └── 角色特化 (character-specific)
                └── Cyrene → 必须使用 ~ 和 ♪

使用方式::

    from agent.persona.tone_injector import ToneInjector

    injector = ToneInjector()
    modifier = injector.generate(
        persona="Cyrene",
        style="healing",
        user_emotions=["sad"],
        stage="deep_talk",
    )
    # modifier.instructions → "用户情绪低落，请使用更温暖治愈的语气..."
    # modifier.system_override → 拼入 System Prompt 的语气指令文本
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
_TONE_CFG = _PERSONA_CFG.get("tone", {})
_STYLES_CFG = _PERSONA_CFG.get("styles", {})


# ==================== 数据结构 ====================

@dataclass
class ToneModifier:
    """语气修改指令。"""
    persona: str = ""                           # 角色名
    style: str = "default"                      # 基础风格
    instructions: list[str] = field(default_factory=list)  # 具体指令列表
    temperature: float = 0.5                    # 建议温度
    system_override: str = ""                   # 拼入 System Prompt 的完整文本

    def to_prompt_text(self) -> str:
        """生成可注入 System Prompt 的语气指令文本。"""
        if not self.system_override:
            return ""
        return f"## 当前语气指令\n{self.system_override}"


# ==================== 语气注入器 ====================

class ToneInjector:
    """动态语气指令生成器。

    将角色灵魂、语气风格、用户情绪、对话阶段等信息
    转化为具体的行为指令文本。

    使用示例::

        injector = ToneInjector()
        modifier = injector.generate(
            persona="Cyrene",
            style="healing",
            user_emotions=["sad"],
            stage="deep_talk",
        )
        print(modifier.system_override)
    """

    # 情绪 → 语气修改器映射
    _EMOTION_MODIFIERS = _TONE_CFG.get("modifiers", {})

    # 对话阶段提示
    _STAGE_HINTS = _TONE_CFG.get("stage_hints", {})

    # 角色特化指令（角色特有的语气规则）
    _CHARACTER_SPECIFICS: dict[str, list[str]] = {
        "Cyrene": [
            "句末使用 ~ 拉长元音，适当使用 ♪ 表示愉快语调",
            '使用亲昵称呼（如「我亲爱的」「可爱的朋友」）',
            '保持积极诗意，即使是讨论悲伤话题也透过「希望」和「美」来叙述',
        ],
        "Columbina": [
            "句子简短、真诚、不加修饰",
            "闭眼感知情感（kuuvahki）比视觉更可靠",
            "保持安静观察者的姿态，不要急于填补沉默",
        ],
        "Ye Shunguang": [
            "使用礼貌温和的语气，适度使用剑道/武道比喻",
            "在给出建议时像前辈一样可靠",
            "偶尔为过于严肃的表达感到害羞",
        ],
        "Zhuang Fangyi": [
            "保持冷静高效，不说废话",
            "可以适当使用干涩的幽默（deadpan humor）",
            "用数据和分析支撑观点，但不要显得冷漠",
        ],
    }

    def generate(
        self,
        persona: str | None = None,
        style: str = "default",
        user_emotions: list[str] | None = None,
        stage: str | None = None,
        topic: str | None = None,
    ) -> ToneModifier:
        """生成动态语气修改指令。

        Args:
            persona: 当前角色名。
            style: 基础语气风格。
            user_emotions: 用户情绪列表。
            stage: 对话阶段（greeting / deep_talk / farewell）。
            topic: 检测到的话题。

        Returns:
            ToneModifier 包含所有语气指令。
        """
        modifier = ToneModifier(
            persona=persona or "",
            style=style,
            temperature=self._get_style_temp(style),
        )

        # 1) 基础风格描述
        style_desc = self._get_style_description(style)
        if style_desc:
            modifier.instructions.append(style_desc)

        # 2) 情绪修正指令
        if user_emotions:
            for emotion in user_emotions[:2]:  # 最多处理前 2 个情绪
                emo_mod = self._get_emotion_modifier(emotion)
                if emo_mod:
                    modifier.instructions.append(emo_mod["instruction"])
                    modifier.temperature += emo_mod.get("temperature_shift", 0)

        # 3) 对话阶段提示
        if stage:
            stage_hint = self._get_stage_hint(stage)
            if stage_hint:
                modifier.instructions.append(stage_hint)

        # 4) 角色特化指令
        if persona:
            char_spec = self._CHARACTER_SPECIFICS.get(persona, [])
            for spec in char_spec:
                modifier.instructions.append(spec)

        # 5) 话题特化提示
        if topic:
            topic_hint = self._get_topic_hint(topic)
            if topic_hint:
                modifier.instructions.append(topic_hint)

        # 钳制 temperature
        modifier.temperature = max(0.1, min(1.0, modifier.temperature))

        # 生成完整的 system_override 文本
        modifier.system_override = self._build_override(modifier)

        logger.debug(
            f"[ToneInjector] 生成: persona={persona}, style={style}, "
            f"emotions={user_emotions}, stage={stage}, "
            f"instructions={len(modifier.instructions)}, temp={modifier.temperature:.2f}"
        )
        return modifier

    # ==================== 各类获取方法 ====================

    def _get_style_description(self, style: str) -> str:
        """获取风格的文字描述。"""
        style_cfg = _STYLES_CFG.get(style, {})
        return style_cfg.get("description", "")

    def _get_style_temp(self, style: str) -> float:
        """获取风格的建议温度。"""
        style_cfg = _STYLES_CFG.get(style, {})
        return style_cfg.get("temperature", 0.5)

    def _get_emotion_modifier(self, emotion: str) -> dict | None:
        """获取情绪对应的语气修改器。"""
        key_map = {
            "angry": "angry_user",
            "sad": "sad_user",
            "urgent": "urgent_user",
            "happy": "happy_user",
        }
        key = key_map.get(emotion, "")
        return self._EMOTION_MODIFIERS.get(key)

    def _get_stage_hint(self, stage: str) -> str | None:
        """获取对话阶段的提示。"""
        stage_cfg = self._STAGE_HINTS.get(stage, {})
        return stage_cfg.get("instruction")

    def _get_topic_hint(self, topic: str) -> str | None:
        """获取话题特化提示。"""
        hints = {
            "anime_recommend": "用户正在寻求动漫推荐，请结合角色特点给出有共鸣的推荐",
            "anime_analysis": "用户需要深度分析，请用角色视角提供独特见解",
            "emotional_support": "用户需要情感陪伴，请优先倾听和共情",
            "tech_support": "用户需要技术支持，请清晰准确地提供帮助",
        }
        return hints.get(topic)

    def _build_override(self, modifier: ToneModifier) -> str:
        """根据指令列表构建完整的 system_override 文本。"""
        if not modifier.instructions:
            return ""

        lines = [
            f"当前角色: {modifier.persona}" if modifier.persona else "",
            f"当前风格: {modifier.style}",
            "",
            "请遵循以下语气指引：",
        ]

        for i, instruction in enumerate(modifier.instructions, 1):
            lines.append(f"{i}. {instruction}")

        # 去空行
        lines = [l for l in lines if l]

        return "\n".join(lines)


# ==================== 模块级实例 ====================

tone_injector = ToneInjector()


# ==================== 便捷函数 ====================

def generate_tone_modifier(
    persona: str | None = None,
    style: str = "default",
    user_emotions: list[str] | None = None,
    stage: str | None = None,
    topic: str | None = None,
) -> ToneModifier:
    """快速生成语气修改指令的便捷函数。"""
    return tone_injector.generate(
        persona=persona,
        style=style,
        user_emotions=user_emotions,
        stage=stage,
        topic=topic,
    )


# ==================== 测试 ====================

if __name__ == "__main__":
    injector = ToneInjector()

    test_cases = [
        ("Cyrene", "healing", ["sad"], "deep_talk", "emotional_support"),
        ("Ye Shunguang", "lively", ["happy"], "greeting", "anime_recommend"),
        ("Zhuang Fangyi", "focused", ["urgent"], None, "tech_support"),
        ("Columbina", "default", [], None, "casual_chat"),
    ]

    for persona, style, emotions, stage, topic in test_cases:
        print(f"\n{'='*60}")
        print(f"角色={persona}, 风格={style}, 情绪={emotions}, 阶段={stage}, 话题={topic}")
        mod = injector.generate(
            persona=persona,
            style=style,
            user_emotions=emotions,
            stage=stage,
            topic=topic,
        )
        print(f"Temperature: {mod.temperature:.2f}")
        print(f"指令数: {len(mod.instructions)}")
        print(mod.system_override[:300])
