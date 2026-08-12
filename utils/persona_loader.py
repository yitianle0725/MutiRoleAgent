"""
角色人设加载器
==============
双模式加载角色人设：

- **新模式 (V2)**：从 ``prompts/soul/*.md`` 加载角色灵魂文件（推荐）
- **旧模式 (V1)**：从 ``prompts/character_*.json`` 加载 Chara Card V2 JSON

设计原则
--------
- **关注点分离**：角色卡只管「怎么说话」（语气/人设/对话风格），
  不管「说什么」（工具调用规则/业务逻辑由 base prompt 控制）。
- **多角色扩展**：``PersonaLoader`` 以 name 为 key 管理多张角色卡，
  运行时通过 middleware 动态切换。
- **渐进迁移**：新架构 (.md) 优先，fallback 到旧架构 (JSON)。
- **与中间件协作**：中间件的 ``dynamic_prompt`` 钩子从
  ``runtime.context["persona"]`` 读取当前角色名，
  调用本模块的 ``build_persona_overlay()`` 拼合最终提示词。
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from utils.logger_handler import logger
from utils.path_tool import get_abs_path


# ==================== 数据结构 ====================

@dataclass
class PersonaCard:
    """角色卡的内部表示，从 Chara Card V2 JSON 解析而来。"""
    name: str
    display_name: str                          # 对话中显示的昵称
    description_md: str                        # 完整 description（markdown）
    # 按标题拆分的段落缓存
    sections: dict[str, str] = field(default_factory=dict)
    first_message: str = ""
    example_messages: str = ""
    avatar_url: str = ""
    tags: list[str] = field(default_factory=list)

    # 用于构造系统提示词的关键段落标题（英文/中文）
    PROMPT_SECTION_TITLES: ClassVar[list[str]] = [
        "1. Profile & Identity",
        "3. Personality",
        "6. Dialogue & Speech Patterns",
        "7. Roleplay Guidelines (System Prompt for AI)",
    ]

    def __post_init__(self):
        """解析 description markdown，按 ``## 标题`` 拆分为段落字典。"""
        if not self.description_md:
            return
        # 匹配 "## N. Title" 或 "## Title" 格式的二级标题
        pattern = re.compile(r'^##\s+(.*?)$', re.MULTILINE)
        splits = pattern.split(self.description_md)
        # splits[0] = 第一个标题之前的内容（通常为空或前言）
        # splits[1] = 第一个标题名, splits[2] = 其内容, splits[3] = 第二个标题名, ...
        if len(splits) <= 1:
            self.sections["_preamble"] = self.description_md
            return
        self.sections["_preamble"] = splits[0].strip()
        for i in range(1, len(splits), 2):
            title = splits[i].strip()
            body = splits[i + 1].strip() if (i + 1) < len(splits) else ""
            self.sections[title] = body

    def build_persona_overlay(self) -> str:
        """将角色卡的关键段落组装为「角色人设提示词叠加层」。

        只抽取对对话行为有影响的段落（身份、性格、说话方式、扮演规则），
        跳过外观描写、背景故事等纯 lore 内容（除非作为上下文需要）。

        Returns:
            可直接拼接到 base prompt 之前的角色人设文本。
        """
        parts: list[str] = []

        # 1) Profile & Identity —— 建立角色自我认知
        profile = self.sections.get("1. Profile & Identity", "")
        if profile:
            parts.append(f"## 角色身份\n{profile}")

        # 2) Personality —— 行为准则
        personality = self.sections.get("3. Personality", "")
        if personality:
            parts.append(f"## 性格与行为准则\n{personality}")

        # 3) Dialogue & Speech Patterns —— 语气/标点/口头禅
        dialogue = self.sections.get("6. Dialogue & Speech Patterns", "")
        if dialogue:
            parts.append(f"## 对话风格与语气要求（必须严格遵守）\n{dialogue}")

        # 4) Roleplay Guidelines —— 给 AI 的扮演指令
        guidelines = self.sections.get("7. Roleplay Guidelines (System Prompt for AI)", "")
        if guidelines:
            parts.append(f"## 扮演规则\n{guidelines}")

        if not parts:
            logger.warning(f"[PersonaCard] 角色卡 '{self.name}' 未提取到任何有效段落，将使用 description 全文")
            return self.description_md

        overlay = "\n\n".join(parts)

        # 强制约束：禁止逐字照搬示例
        overlay += (
            "\n\n**重要**：以上对话示例仅供语气风格参考，"
            "你必须根据当前对话场景生成全新的、自然的回复，"
            "严禁照搬或改写示例中的原句。"
        )
        return overlay

    def build_full_context(self) -> str:
        """构建完整角色上下文（含背景故事 + 外观，适合初遇场景）。"""
        parts: list[str] = [self.build_persona_overlay()]

        background = self.sections.get("5. Background Story", "")
        if background:
            parts.append(f"## 背景故事\n{background}")

        appearance = self.sections.get("2. Appearance", "")
        if appearance:
            parts.append(f"## 外观描述\n{appearance}")

        return "\n\n".join(parts)


# ==================== 加载器 ====================

class PersonaLoader:
    """角色卡管理器，负责加载、缓存与查询。

    使用方式::

        loader = PersonaLoader()
        loader.load_from_json("prompts/character_Cyrene.json")
        overlay = loader.build_overlay("Cyrene")   # → 拼入 base prompt
        context = loader.build_full("Cyrene")       # → 完整角色上下文
    """

    def __init__(self):
        self._personas: dict[str, PersonaCard] = {}

    # ---- 加载 ----

    def load_soul_md(self, persona_name: str) -> str | None:
        """从 ``prompts/soul/`` 加载角色灵魂 .md 文件（V2 新架构）。

        优先使用此方法获取角色人设——.md 文件比 JSON 更易于编辑和维护。

        Args:
            persona_name: 角色名（如 "Cyrene"、"Ye Shunguang"）。

        Returns:
            灵魂文件内容；若文件不存在则返回 None。
        """
        from prompts.composer import _load_soul

        # 先尝试 composer 的 soul 加载
        soul_content = _load_soul(persona_name)
        if soul_content:
            logger.info(f"[PersonaLoader] 从 soul/{persona_name} 加载角色灵魂 (V2)")
            return soul_content

        # fallback: 尝试从旧的 PersonaCard 构建
        card = self._personas.get(persona_name)
        if card:
            logger.info(f"[PersonaLoader] 回退到 JSON 角色卡: {persona_name}")
            return card.build_persona_overlay()

        # 尝试懒加载 JSON
        self._ensure_loaded(persona_name)
        card = self._personas.get(persona_name)
        if card:
            return card.build_persona_overlay()

        return None

    def _ensure_loaded(self, name: str):
        """内部懒加载（不依赖模块级 ensure_persona_loaded，避免循环导入）。"""
        if name and name not in self._personas:
            path = PERSONA_FILES.get(name)
            if path:
                abs_path = get_abs_path(path)
                if os.path.exists(abs_path):
                    self.load_from_json(path)
                    logger.info(f"[PersonaLoader] 懒加载角色卡: {name}")

    def load_from_json(self, relative_path: str) -> PersonaCard:
        """从 Chara Card V2 JSON 文件加载一张角色卡。

        Args:
            relative_path: 相对于项目根目录的 JSON 文件路径。

        Returns:
            解析后的 PersonaCard 实例。

        Raises:
            FileNotFoundError: 文件不存在。
            json.JSONDecodeError: JSON 格式错误。
        """
        abs_path = get_abs_path(relative_path)

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"角色卡文件不存在: {abs_path}")

        with open(abs_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # 兼容 Chara Card V2 格式
        spec = raw.get("spec", "")
        if spec != "chara_card_v2":
            logger.warning(f"[PersonaLoader] 未知的角色卡格式 spec={spec}，尝试兼容解析")

        data = raw.get("data", raw)  # 若无 data 包裹则退化为平铺 JSON
        name = data.get("name", Path(abs_path).stem)

        card = PersonaCard(
            name=name,
            display_name=data.get("name", name),
            description_md=data.get("description", ""),
            first_message=data.get("first_mes", ""),
            example_messages=data.get("mes_example", ""),
            avatar_url=data.get("avatar", ""),
            tags=data.get("tags", []),
        )

        self._personas[name] = card
        logger.info(f"[PersonaLoader] 已加载角色卡: {name} (sections={list(card.sections.keys())})")
        return card

    # ---- 查询 ----

    def get(self, name: str) -> PersonaCard | None:
        """按角色名获取角色卡，未加载则返回 None。"""
        return self._personas.get(name)

    def build_overlay(self, name: str) -> str:
        """构建指定角色的 persona overlay（仅对话行为相关段落）。

        若角色未加载，返回空字符串（即无 persona 模式）。
        """
        card = self._personas.get(name)
        if card is None:
            logger.warning(f"[PersonaLoader] 角色 '{name}' 未加载，回退到无 persona 模式")
            return ""
        return card.build_persona_overlay()

    def build_full(self, name: str) -> str:
        """构建指定角色的完整上下文（含背景故事 + 外观）。"""
        card = self._personas.get(name)
        if card is None:
            return ""
        return card.build_full_context()

    @property
    def available_names(self) -> list[str]:
        """返回所有已加载的角色名。"""
        return list(self._personas.keys())

    @property
    def persona_count(self) -> int:
        return len(self._personas)


# ==================== 模块级单例 ====================

# 全局唯一实例，供 middleware 和 prompt_loader 直接引用
persona_loader = PersonaLoader()


# ==================== 便捷函数（供 prompt_loader 调用） ====================

def load_persona_overlay(persona_name: str) -> str:
    """获取 persona overlay（V2 soul .md 优先，fallback JSON）。

    如果 persona_name 为 None / 空字符串 / "none"，返回空字符串。
    """
    if not persona_name or persona_name.lower() == "none":
        return ""

    # V2 优先级: soul/*.md
    soul_md = persona_loader.load_soul_md(persona_name)
    if soul_md:
        return soul_md

    # V1 fallback: Chara Card JSON
    ensure_persona_loaded(persona_name)
    return persona_loader.build_overlay(persona_name)


def load_persona_full(persona_name: str) -> str:
    """从已加载的角色卡中获取完整上下文。"""
    if not persona_name or persona_name.lower() == "none":
        return ""
    return persona_loader.build_full(persona_name)


# 角色名 → JSON 文件路径映射
PERSONA_FILES: dict[str, str] = {
    "Cyrene":          "prompts/character_Cyrene.json",
    "Columbina":       "prompts/character_Columbina.json",
    "Ye Shunguang":    "prompts/character_Ye-shunguang.json",
    "Zhuang Fangyi":   "prompts/character_Zhuang-fangyi.json",
}


def init_default_personas(names: list[str] | None = None):
    """应用启动时预加载指定角色卡（默认只加载 Cyrene，懒加载其余）。

    Args:
        names: 角色名列表，None 表示只加载 Cyrene。
    """
    if names is None:
        names = ["Cyrene"]
    for name in names:
        path = PERSONA_FILES.get(name)
        if path:
            abs_path = get_abs_path(path)
            if os.path.exists(abs_path):
                persona_loader.load_from_json(path)
            else:
                logger.info(f"[init_default_personas] 跳过不存在的角色卡: {path}")

    logger.info(f"[init_default_personas] 已加载 {persona_loader.persona_count} 张角色卡: "
                f"{persona_loader.available_names}")


def ensure_persona_loaded(name: str):
    """懒加载指定角色卡（如果尚未加载）。"""
    if name and name not in persona_loader.available_names:
        path = PERSONA_FILES.get(name)
        if path:
            abs_path = get_abs_path(path)
            if os.path.exists(abs_path):
                persona_loader.load_from_json(path)
                logger.info(f"[ensure_persona] 懒加载角色卡: {name}")
            else:
                logger.warning(f"[ensure_persona] 角色卡不存在: {path}")
