"""
角色灵魂加载器
==============
从 ``prompts/roles/{slug}/soul/*.md`` 加载角色灵魂文件，支持缓存、热重载和元数据提取。

加载层（按注入顺序）:
- ``prompts/roles/_shared/base.md``    共享扮演底座（渲染 {{character_name}} 后最先注入）
- ``prompts/roles/{slug}/soul/base.md`` 角色基本信息（身份/性格/说话方式/扮演规则速览）
- ``prompts/roles/{slug}/soul/soul.md`` 角色行为细则（权威人格宪法）

相比 composer.py 的 _load_soul()，增强点：
- 段落解析：将灵魂文件按 ## 标题拆分为结构化段落
- 元数据提取：标签、最佳风格、展示名
- 热重载：支持运行时清除缓存重新加载
- 角色列表：列出所有可用角色及元数据

使用方式::

    from agent.persona.soul_loader import SoulLoader

    loader = SoulLoader()
    soul = loader.load("Cyrene")
    # soul.full_text — 完整灵魂文本
    # soul.sections — 按标题拆分的段落
    # soul.metadata — 角色元数据
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
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
_CHAR_CFG = _PERSONA_CFG.get("characters", {})

# 路径常量
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_ROLES_DIR = _PROMPTS_DIR / "roles"
_SHARED_BASE_FILE = _ROLES_DIR / "_shared" / "base.md"


# ==================== 数据结构 ====================

@dataclass
class SoulMetadata:
    """角色元数据。"""
    name: str                               # 内部名（如 "Cyrene"）
    display_name: str                       # 展示名（如 "昔涟"）
    emoji: str = ""                         # 角色 emoji
    tags: list[str] = field(default_factory=list)
    best_styles: list[str] = field(default_factory=list)
    description: str = ""
    soul_file: str = ""


@dataclass
class LoadedSoul:
    """已加载的角色灵魂。"""
    name: str
    full_text: str                          # 完整文本
    sections: dict[str, str]                # 按 ## 标题拆分的段落
    metadata: SoulMetadata                  # 角色元数据
    char_count: int = 0                     # 字符数
    line_count: int = 0                     # 行数

    @property
    def identity(self) -> str:
        """身份段落。"""
        return self.sections.get("身份", "")

    @property
    def personality(self) -> str:
        """性格段落。"""
        return self.sections.get("性格", "")

    @property
    def speech(self) -> str:
        """说话方式段落。"""
        return self.sections.get("说话方式", "")

    @property
    def rules(self) -> str:
        """扮演规则段落。"""
        return self.sections.get("扮演规则", "")

    def get_core_prompt(self) -> str:
        """获取核心扮演提示词。

        旧平铺 soul 文件的全部内容就是「身份 + 性格 + 说话方式 + 规则」四个
        段落；新分层结构下等价物是完整灵魂层（共享底座 + base.md + soul.md），
        因此直接返回 full_text。
        """
        return self.full_text


# ==================== 加载器 ====================

class SoulLoader:
    """角色灵魂加载器。

    负责从 prompts/roles/{slug}/soul/ 加载角色灵魂文件，
    解析结构化段落，提取元数据。

    使用示例::

        loader = SoulLoader()
        soul = loader.load("Cyrene")
        print(soul.metadata.display_name)  # "昔涟"
        print(soul.personality)            # 性格段落
    """

    def __init__(self):
        self._cache: dict[str, LoadedSoul] = {}
        self._roles_dir = _ROLES_DIR

    # ==================== 加载 ====================

    def _resolve_slug(self, name: str) -> str:
        """解析角色包目录名（slug）。

        优先级: persona.yaml 的 slug → soul_file 去扩展名 → composer 映射。
        """
        char_cfg = _CHAR_CFG.get(name, {})
        slug = char_cfg.get("slug", "")
        if slug:
            return slug

        filename = char_cfg.get("soul_file", "")
        if not filename:
            from prompts.composer import _PERSONA_TO_SLUG
            filename = _PERSONA_TO_SLUG.get(name, "")
        return filename.removesuffix(".md") if filename else ""

    def load(self, name: str) -> LoadedSoul | None:
        """加载指定角色的灵魂。

        Args:
            name: 角色名（如 "Cyrene"、"Ye Shunguang"）。

        Returns:
            LoadedSoul 实例；若文件不存在则返回 None。
        """
        # 检查缓存
        if name in self._cache:
            return self._cache[name]

        slug = self._resolve_slug(name)
        if not slug:
            logger.warning(f"[SoulLoader] 未知角色: {name}")
            return None

        soul_dir = self._roles_dir / slug / "soul"
        if not soul_dir.is_dir():
            logger.warning(f"[SoulLoader] 灵魂目录不存在: {soul_dir}")
            return None

        # 读取文件（共享底座 + base + soul）
        parts: list[str] = []
        shared_base = self._load_shared_base(name)
        if shared_base:
            parts.append(shared_base)

        for filename in ("base.md", "soul.md"):
            filepath = soul_dir / filename
            if not filepath.exists():
                logger.warning(f"[SoulLoader] 灵魂文件不存在: {filepath}")
                continue
            try:
                parts.append(filepath.read_text(encoding="utf-8").strip())
            except OSError as e:
                logger.error(f"[SoulLoader] 读取失败: {filepath} — {e}")

        if not parts:
            return None

        full_text = "\n\n---\n\n".join(parts)

        # 解析段落
        sections = self._parse_sections(full_text)

        # 构建元数据
        char_cfg = _CHAR_CFG.get(name, {})
        metadata = SoulMetadata(
            name=name,
            display_name=char_cfg.get("display_name", name),
            emoji=char_cfg.get("emoji", ""),
            tags=char_cfg.get("tags", []),
            best_styles=char_cfg.get("best_styles", ["default"]),
            description=char_cfg.get("description", ""),
            soul_file=slug,
        )

        soul = LoadedSoul(
            name=name,
            full_text=full_text,
            sections=sections,
            metadata=metadata,
            char_count=len(full_text),
            line_count=full_text.count("\n") + 1,
        )

        # 缓存
        self._cache[name] = soul
        logger.info(
            f"[SoulLoader] 已加载角色: {name} "
            f"({metadata.display_name}) — "
            f"{soul.char_count} 字符, {len(sections)} 段落"
        )
        return soul

    def _load_shared_base(self, name: str) -> str:
        """加载共享扮演底座并渲染角色名占位符。"""
        try:
            text = _SHARED_BASE_FILE.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning(f"[SoulLoader] 共享底座读取失败: {_SHARED_BASE_FILE} — {e}")
            return ""
        display = _CHAR_CFG.get(name, {}).get("display_name", name)
        return text.replace("{{character_name}}", display)

    def _parse_sections(self, text: str) -> dict[str, str]:
        """将 Markdown 文本按 ## 标题拆分为段落字典。"""
        sections: dict[str, str] = {}

        # 匹配 ## 标题
        pattern = re.compile(r'^##\s+(.*?)$', re.MULTILINE)
        splits = pattern.split(text)

        if len(splits) <= 1:
            sections["_full"] = text
            return sections

        # splits[0] = 第一个标题之前的前言
        preamble = splits[0].strip()
        if preamble:
            sections["_preamble"] = preamble

        # splits[1]=标题1, splits[2]=内容1, ...
        for i in range(1, len(splits), 2):
            title = splits[i].strip()
            body = splits[i + 1].strip() if (i + 1) < len(splits) else ""
            sections[title] = body

        sections["_full"] = text
        return sections

    # ==================== 缓存管理 ====================

    def reload(self, name: str) -> LoadedSoul | None:
        """热重载指定角色（清除缓存后重新加载）。"""
        self._cache.pop(name, None)
        logger.info(f"[SoulLoader] 热重载角色: {name}")
        return self.load(name)

    def reload_all(self):
        """热重载所有已缓存的角色。"""
        names = list(self._cache.keys())
        self._cache.clear()
        for name in names:
            self.load(name)
        logger.info(f"[SoulLoader] 已重载全部 {len(names)} 个角色")

    def reload_all_from_disk(self) -> list[LoadedSoul]:
        """清空缓存并从磁盘重新读取全部角色人设文件。"""
        self._cache.clear()
        loaded = self.list_all()
        logger.info("[SoulLoader] 已从磁盘重新读取全部角色: %d", len(loaded))
        return loaded

    def clear_cache(self):
        """清除所有缓存。"""
        self._cache.clear()
        logger.info("[SoulLoader] 缓存已清除")

    # ==================== 查询 ====================

    def get(self, name: str) -> LoadedSoul | None:
        """获取已缓存的角色（不触发加载）。"""
        return self._cache.get(name)

    def list_all(self) -> list[LoadedSoul]:
        """列出所有可用角色（触发加载）。"""
        result: list[LoadedSoul] = []
        for name in _CHAR_CFG:
            soul = self.load(name)
            if soul:
                result.append(soul)
        return result

    @property
    def available_names(self) -> list[str]:
        """返回所有可用角色名。"""
        return list(_CHAR_CFG.keys())

    @property
    def loaded_count(self) -> int:
        """已缓存的角色数。"""
        return len(self._cache)


# ==================== 模块级实例 ====================

soul_loader = SoulLoader()


# ==================== 便捷函数 ====================

def load_soul(persona_name: str) -> LoadedSoul | None:
    """快速加载角色灵魂的便捷函数。"""
    return soul_loader.load(persona_name)


def get_soul_metadata(persona_name: str) -> SoulMetadata | None:
    """快速获取角色元数据的便捷函数。"""
    soul = soul_loader.load(persona_name)
    return soul.metadata if soul else None


# ==================== 测试 ====================

if __name__ == "__main__":
    loader = SoulLoader()

    for name in ["Cyrene", "Columbina", "Ye Shunguang", "Zhuang Fangyi"]:
        soul = loader.load(name)
        if soul:
            print(f"\n{'='*60}")
            print(f"角色: {soul.metadata.display_name} {soul.metadata.emoji}")
            print(f"标签: {', '.join(soul.metadata.tags)}")
            print(f"最佳风格: {', '.join(soul.metadata.best_styles)}")
            print(f"段落: {list(soul.sections.keys())}")
            print(f"字符数: {soul.char_count}")
            print(f"身份: {soul.identity[:100]}...")
        else:
            print(f"FAIL: 无法加载 {name}")

    print(f"\n已加载: {loader.loaded_count} 个角色")
    print(f"可用角色: {loader.available_names}")
