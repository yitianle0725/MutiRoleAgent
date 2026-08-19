"""
Persona Engine 主控制器
=======================
协调 Soul Loader、Style Picker、Worldbook Retriever、Tone Injector
四大组件，为每轮对话生成完整的角色提示词。

数据流::

    用户输入 + CITA 分析 + 对话上下文
                │
                ▼
    ┌────────────────────────┐
    │ PersonaEngine.process()│
    │                        │
    │ 1. SoulLoader.load()   │ ← 加载角色灵魂
    │ 2. StylePicker.pick()  │ ← 选择最佳风格
    │ 3. WorldbookRetriever  │ ← 检索相关世界观
    │    .retrieve()         │
    │ 4. ToneInjector        │ ← 生成语气指令
    │    .generate()         │
    │                        │
    │ 5. 组装最终 Prompt      │
    └──────────┬─────────────┘
               │
               ▼
         PersonaResult
         ├── persona_prompt (角色扮演提示词)
         ├── worldbook_text (世界观知识)
         ├── tone_override  (语气指令)
         ├── style          (选中风格)
         └── transition_msg (切换消息)

使用方式::

    from agent.persona import PersonaEngine

    engine = PersonaEngine()
    result = engine.process(
        persona="Cyrene",
        user_emotions=["sad"],
        topic="emotional_support",
        user_query="我今天心情不太好",
    )
    # result.persona_prompt → 完整角色提示词
    # result.style → "healing"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from utils.logger_handler import logger

# 配置
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
_CHAR_CFG = _PERSONA_CFG.get("characters", {})
_TRANSITION_CFG = _PERSONA_CFG.get("transition", {})


# ==================== 数据结构 ====================

@dataclass
class PersonaResult:
    """Persona Engine 处理结果。"""
    # 组装完成的角色提示词
    persona_prompt: str = ""
    # 世界观知识文本
    worldbook_text: str = ""
    # 语气指令覆盖
    tone_override: str = ""
    # 选中的风格
    style: str = "default"
    # 角色切换时的过渡消息（无切换则为空）
    transition_msg: str = ""
    # 推荐的角色（用户情绪强烈时）
    recommended_characters: list[str] = field(default_factory=list)
    # 元数据
    persona_name: str = ""
    persona_display: str = ""
    persona_emoji: str = ""
    temperature: float = 0.5
    # 各组件信息（调试用）
    style_reason: str = ""
    worldbook_entries: int = 0
    tone_instructions: int = 0


# ==================== Persona Engine ====================

class PersonaEngine:
    """Persona Engine 主控制器。

    整合四大组件：
    - SoulLoader: 角色灵魂
    - StylePicker: 风格选择
    - WorldbookRetriever: 世界观检索
    - ToneInjector: 语气指令

    使用示例::

        engine = PersonaEngine()

        # 每轮对话开始时调用
        result = engine.process(
            persona="Cyrene",
            user_query="推荐几部热血番",
            user_emotions=["happy"],
            topic="anime_recommend",
        )
        # 将 result.persona_prompt 注入 System Prompt
    """

    def __init__(self):
        from agent.persona.soul_loader import SoulLoader
        from agent.persona.style_picker import StylePicker
        from agent.persona.worldbook_retriever import WorldbookRetriever
        from agent.persona.tone_injector import ToneInjector

        self.soul_loader = SoulLoader()
        self.style_picker = StylePicker()
        self.worldbook_retriever = WorldbookRetriever()
        self.tone_injector = ToneInjector()

        # 切换历史（记录上一次角色）
        self._last_persona: str | None = None

    # ==================== 主入口 ====================

    def process(
        self,
        persona: str | None = None,
        style: str | None = None,
        user_query: str = "",
        user_emotions: list[str] | None = None,
        topic: str | None = None,
        entities: list | None = None,
        conversation_stage: str | None = None,
        history_summary: str = "",
    ) -> PersonaResult:
        """处理一轮对话的角色提示词生成。

        Args:
            persona: 当前角色名（None = 无角色模式）。
            style: 手动指定的风格（None = 自动选择）。
            user_query: 用户输入文本。
            user_emotions: CITA 检测到的用户情绪列表。
            topic: 检测到的话题标签。
            entities: CITA 提取的实体列表。
            conversation_stage: 对话阶段（greeting / deep_talk / farewell）。
            history_summary: 对话历史摘要（用于跨角色记忆）。

        Returns:
            PersonaResult 包含所有生成的提示词组件。
        """
        result = PersonaResult()

        # 无角色模式 → 返回空结果
        if not persona:
            logger.debug("[PersonaEngine] 无角色模式，跳过处理")
            return result

        # ---- 1) 加载角色灵魂 ----
        soul = self.soul_loader.load(persona)
        if not soul:
            logger.warning(f"[PersonaEngine] 角色 '{persona}' 加载失败，跳过")
            return result

        result.persona_name = persona
        result.persona_display = soul.metadata.display_name
        result.persona_emoji = soul.metadata.emoji

        # ---- 2) 风格选择 ----
        style_selection = self.style_picker.pick(
            persona=persona,
            user_emotions=user_emotions,
            topic=topic,
            manual_style=style,
            conversation_stage=conversation_stage,
        )
        result.style = style_selection.style
        result.style_reason = style_selection.reason
        result.temperature = style_selection.temperature

        logger.info(
            f"[PersonaEngine] 角色={persona}, 风格={style_selection.style} "
            f"(source={style_selection.source}, reason={style_selection.reason})"
        )

        # ---- 3) 世界观知识检索 ----
        worldbook_entries = self.worldbook_retriever.retrieve(
            query=user_query,
            persona=persona,
            entities=entities,
            topic=topic,
        )
        result.worldbook_text = self.worldbook_retriever.format_entries(worldbook_entries)
        result.worldbook_entries = len(worldbook_entries)

        # ---- 4) 语气指令生成 ----
        tone_mod = self.tone_injector.generate(
            persona=persona,
            style=style_selection.style,
            user_emotions=user_emotions,
            stage=conversation_stage,
            topic=topic,
        )
        result.tone_override = tone_mod.system_override
        result.tone_instructions = len(tone_mod.instructions)
        result.temperature = tone_mod.temperature

        # ---- 5) 组装最终角色提示词 ----
        result.persona_prompt = self._assemble_prompt(soul, result, history_summary)

        # ---- 6) 角色切换检测 ----
        if self._last_persona and self._last_persona != persona:
            result.transition_msg = self._build_transition(
                self._last_persona, persona
            )
        self._last_persona = persona

        # ---- 7) 角色推荐（强情绪时） ----
        if user_emotions and len(user_emotions) > 0:
            primary = user_emotions[0]
            if primary in ("angry", "sad", "urgent"):
                chars, _ = self.style_picker.recommend_character_with_reason(
                    user_emotions
                )
                result.recommended_characters = chars

        logger.info(
            f"[PersonaEngine] 处理完成: persona={persona}, style={result.style}, "
            f"worldbook={result.worldbook_entries}条, "
            f"tone={result.tone_instructions}条指令, "
            f"prompt_len={len(result.persona_prompt)}字符"
        )
        return result

    # ==================== Prompt 组装 ====================

    def _assemble_prompt(
        self,
        soul,
        result: PersonaResult,
        history_summary: str = "",
    ) -> str:
        """组装最终的角色扮演提示词。

        组装顺序:
        1. 角色扮演模式声明
        2. 角色核心人设（身份 + 性格 + 说话方式 + 规则）
        3. 世界观知识（按需检索）
        4. 语气指令
        """
        parts: list[str] = []

        # 1) 角色扮演模式声明
        header = (
            f"## ⚠️ 角色扮演模式\n"
            f"你现在正在扮演角色「{result.persona_display}」"
            f"（{result.persona_name}）{result.persona_emoji}。\n"
            f"必须严格遵循以下人设进行对话，"
            f"同时保持助手的功能能力（推荐动漫、查询天气等）。"
        )
        parts.append(header)

        # 2) 角色核心人设
        core = soul.get_core_prompt()
        if core:
            parts.append(core)

        # 3) 跨角色记忆
        if history_summary:
            parts.append(f"## 对话历史摘要（跨角色记忆）\n{history_summary}")

        # 4) 世界观知识
        if result.worldbook_text:
            parts.append(result.worldbook_text)

        # 5) 语气指令
        if result.tone_override:
            parts.append(f"## 当前语气指令\n{result.tone_override}")

        return "\n\n---\n\n".join(parts)

    # ==================== 角色切换 ====================

    def switch_character(
        self, new_persona: str, old_persona: str | None = None
    ) -> str:
        """切换角色并生成过渡消息。

        Args:
            new_persona: 新角色名。
            old_persona: 旧角色名（None = 首次选择角色）。

        Returns:
            过渡消息文本（展示给用户）。
        """
        old = old_persona or self._last_persona
        self._last_persona = new_persona

        if not old:
            # 首次选择角色
            soul = self.soul_loader.load(new_persona)
            if soul:
                return (
                    f"{soul.metadata.emoji} **角色切换**: "
                    f"现在是「{soul.metadata.display_name}」\n\n"
                    f"{soul.metadata.description}"
                )
            return f"已切换角色为: {new_persona}"

        return self._build_transition(old, new_persona)

    def _build_transition(self, old_name: str, new_name: str) -> str:
        """构建角色切换过渡消息。"""
        old_soul = self.soul_loader.get(old_name)
        new_soul = self.soul_loader.load(new_name)

        if not new_soul:
            return f"已切换角色: {old_name} → {new_name}"

        old_display = old_soul.metadata.display_name if old_soul else old_name
        new_display = new_soul.metadata.display_name
        new_emoji = new_soul.metadata.emoji
        new_desc = new_soul.metadata.description

        return (
            f"{new_emoji} **角色切换**: {old_display} → {new_display}\n\n"
            f"{new_desc}"
        )

    def reset(self):
        """重置角色状态。"""
        self._last_persona = None
        logger.info("[PersonaEngine] 角色状态已重置")

    # ==================== 查询 ====================

    def list_characters(self) -> list[dict]:
        """列出所有可用角色及其信息。"""
        result = []
        for name, cfg in _CHAR_CFG.items():
            soul = self.soul_loader.get(name)
            result.append({
                "name": name,
                "display_name": cfg.get("display_name", name),
                "emoji": cfg.get("emoji", ""),
                "tags": cfg.get("tags", []),
                "description": cfg.get("description", ""),
                "best_styles": cfg.get("best_styles", []),
                "loaded": soul is not None,
            })
        return result

    def get_current_persona(self) -> str | None:
        """获取当前角色名。"""
        return self._last_persona

    # ==================== 缓存管理 ====================

    def reload_personas_from_disk(self) -> None:
        """Agent 启动时刷新全部角色文件，避免沿用旧的人设缓存。"""
        self.soul_loader.reload_all_from_disk()
        from prompts.composer import clear_cache
        clear_cache()
        logger.info("[PersonaEngine] 已重新读取磁盘上的全部角色人设")

    def clear_cache(self):
        """清除所有组件缓存（用于热重载）。"""
        self.soul_loader.clear_cache()
        self.worldbook_retriever.clear_cache()
        logger.info("[PersonaEngine] 所有缓存已清除")

    def reload_soul(self, persona: str):
        """热重载指定角色的灵魂文件。"""
        self.soul_loader.reload(persona)
        logger.info(f"[PersonaEngine] 热重载角色: {persona}")


# ==================== 模块级实例 ====================

persona_engine = PersonaEngine()


# ==================== 便捷函数 ====================

def process_persona(
    persona: str | None = None,
    style: str | None = None,
    user_query: str = "",
    user_emotions: list[str] | None = None,
    topic: str | None = None,
    entities: list | None = None,
) -> PersonaResult:
    """快速生成角色提示词的便捷函数。"""
    return persona_engine.process(
        persona=persona,
        style=style,
        user_query=user_query,
        user_emotions=user_emotions,
        topic=topic,
        entities=entities,
    )


# ==================== 测试 ====================

if __name__ == "__main__":
    engine = PersonaEngine()

    # 测试基本流程
    print("=" * 60 + "\n测试 1: Cyrene + 情绪 sad")
    result = engine.process(
        persona="Cyrene",
        user_query="我今天心情不太好",
        user_emotions=["sad"],
        topic="emotional_support",
    )
    print(f"角色: {result.persona_display} {result.persona_emoji}")
    print(f"风格: {result.style} (reason: {result.style_reason})")
    print(f"世界观条目: {result.worldbook_entries}")
    print(f"语气指令: {result.tone_instructions}")
    print(f"温度: {result.temperature}")
    print(f"推荐角色: {result.recommended_characters}")
    print(f"角色提示词长度: {len(result.persona_prompt)} 字符")
    print(f"\n--- 提示词前 300 字符 ---\n{result.persona_prompt[:300]}...")

    print("\n" + "=" * 60 + "\n测试 2: 切换角色 Cyrene → Columbina")
    msg = engine.switch_character("Columbina")
    print(msg)

    print("\n" + "=" * 60 + "\n测试 3: Ye Shunguang + 情绪 happy")
    result = engine.process(
        persona="Ye Shunguang",
        user_query="推荐几部热血番给我！",
        user_emotions=["happy"],
        topic="anime_recommend",
    )
    print(f"角色: {result.persona_display} {result.persona_emoji}")
    print(f"风格: {result.style} (reason: {result.style_reason})")
    print(f"温度: {result.temperature}")

    print("\n" + "=" * 60 + "\n测试 4: Zhuang Fangyi + tech_support")
    result = engine.process(
        persona="Zhuang Fangyi",
        user_query="帮我分析一下进击的巨人的制作水准",
        user_emotions=[],
        topic="anime_analysis",
    )
    print(f"角色: {result.persona_display} {result.persona_emoji}")
    print(f"风格: {result.style} (reason: {result.style_reason})")

    print("\n" + "=" * 60 + "\n测试 5: 无角色模式")
    result = engine.process(persona=None)
    print(f"无角色模式: persona_prompt 为空 = {not bool(result.persona_prompt)}")

    print("\n" + "=" * 60 + "\n所有角色:")
    for c in engine.list_characters():
        print(f"  {c['emoji']} {c['display_name']} ({c['name']}) — {c['description'][:40]}...")

    print("\n✅ Persona Engine 测试完成")
