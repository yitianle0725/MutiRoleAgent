"""
Prompt 动态组合器
=================
按 ``角色灵魂 + 语气风格 + 世界观 + 系统规则 + 动态上下文`` 五层结构
组装最终的系统提示词。

设计原则
--------
- **分层组装**: 每层独立文件，按需组合，避免巨型单文件
- **渐进迁移**: 新架构 (.md) 优先，fallback 到旧架构 (YAML/JSON)
- **缓存友好**: 文件内容在首次加载后缓存，避免重复 I/O

使用方式::

    from prompts.composer import compose_prompt

    prompt = compose_prompt(
        persona="Cyrene",
        style="lively",
        skills_summary="...",
        cita_overlay="...",
        user_profile="...",
    )
"""

from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional

from utils.logger_handler import logger

# ==================== 路径常量 ====================

_PROMPTS_DIR = Path(__file__).resolve().parent
_SOUL_DIR = _PROMPTS_DIR / "soul"
_STYLES_DIR = _PROMPTS_DIR / "styles"
_WORLDBOOK_DIR = _PROMPTS_DIR / "worldbook"
_SYSTEM_DIR = _PROMPTS_DIR / "system"

# 角色名 → soul 文件名映射
_PERSONA_TO_SOUL: dict[str, str] = {
    "Cyrene":          "cyrene.md",
    "Columbina":       "columbina.md",
    "Ye Shunguang":    "ye-shunguang.md",
    "Zhuang Fangyi":   "zhuang-fangyi.md",
}

# 风格名 → style 文件名映射
_STYLE_FILES: dict[str, str] = {
    "default":  "default.md",
    "lively":   "lively.md",
    "healing":  "healing.md",
    "serious":  "serious.md",
}


# ==================== 文件读取 (带缓存) ====================

@lru_cache(maxsize=32)
def _read_file(path: Path) -> str:
    """读取文件内容，带 LRU 缓存。"""
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError) as e:
        logger.warning(f"[Composer] 无法读取文件: {path} — {e}")
        return ""


# ==================== 各层加载 ====================

def _load_system_base() -> str:
    """加载系统基础规则层（tools + safety + output）。

    这是最底层的 Prompt，无论有无角色都始终包含。
    """
    parts: list[str] = []
    for name in ("tools", "safety", "output"):
        content = _read_file(_SYSTEM_DIR / f"{name}.md")
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts) if parts else ""


def _load_worldbook() -> str:
    """加载共享世界观知识（world + characters + glossary）。"""
    parts: list[str] = []
    for name in ("world", "characters", "glossary"):
        content = _read_file(_WORLDBOOK_DIR / f"{name}.md")
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts) if parts else ""


def _load_soul(persona_name: str) -> str:
    """加载角色灵魂文件。

    Args:
        persona_name: 角色名（如 "Cyrene"、"Ye Shunguang"）。

    Returns:
        灵魂文件内容；若文件不存在则返回空字符串。
    """
    filename = _PERSONA_TO_SOUL.get(persona_name)
    if not filename:
        logger.warning(f"[Composer] 未知角色: {persona_name}")
        return ""
    return _read_file(_SOUL_DIR / filename)


def _load_style(style_name: str) -> str:
    """加载语气风格文件。

    Args:
        style_name: 风格名（default / lively / healing / serious）。

    Returns:
        风格文件内容；若文件不存在则返回空字符串。
    """
    filename = _STYLE_FILES.get(style_name, _STYLE_FILES["default"])
    return _read_file(_STYLES_DIR / filename)


# ==================== 主组合函数 ====================

def compose_prompt(
    persona: Optional[str] = None,
    style: Optional[str] = None,
    skills_summary: str = "",
    cita_overlay: str = "",
    user_profile: str = "",
    *,
    _system_base: Optional[str] = None,
    _worldbook: Optional[str] = None,
) -> str:
    """组装最终的系统提示词。

    组装顺序 (从上到下):
    1. 用户画像 (如有)
    2. 系统基础规则 (tools + safety + output) —— 始终包含
    3. 共享世界观 (如有 persona)
    4. 角色灵魂 + 语气风格 (如有 persona)
    5. Skill 摘要 (如有)
    6. CITA 意图覆盖层 (如有)

    Args:
        persona:        角色名，None 表示无角色模式（默认助手）。
        style:          语气风格名，None 表示 default。
        skills_summary: Skill 系统摘要文本。
        cita_overlay:   CITA 意图分类结果覆盖层。
        user_profile:   用户画像文本。

    Returns:
        组装完成的系统提示词字符串。
    """
    parts: list[str] = []

    # ---- Layer 0: 用户画像（最早注入，让后续 prompt 能引用） ----
    if user_profile:
        parts.append(user_profile)

    # ---- Layer 1: 系统基础规则（始终包含） ----
    system_base = _system_base if _system_base is not None else _load_system_base()
    if system_base:
        parts.append(system_base)

    # ---- Layer 2-3: 角色模式 ----
    if persona:
        # 共享世界观
        worldbook = _worldbook if _worldbook is not None else _load_worldbook()
        if worldbook:
            parts.append(worldbook)

        # 角色灵魂
        soul = _load_soul(persona)
        if soul:
            # 附上风格指引
            style_name = style or "default"
            style_content = _load_style(style_name)
            if style_content:
                soul = f"{soul}\n\n---\n\n## 当前语气风格: {style_name}\n{style_content}"

            persona_header = (
                f"## ⚠️ 角色扮演模式\n"
                f"你现在正在扮演角色「{persona}」。"
                f"必须严格遵循以下人设进行对话，"
                f"同时保持助手的功能能力（推荐动漫、查询天气等）。\n\n"
                f"{soul}"
            )
            parts.append(persona_header)

    # ---- Layer 4: Skill 摘要 ----
    if skills_summary:
        skill_section = (
            "## 可用 Skill（通过 invoke_skill 调用）\n"
            "当用户任务匹配以下 Skill 时，先调 `invoke_skill(skill_name)` "
            "获取详细指令，再按指令执行。\n\n"
            f"{skills_summary}"
        )
        parts.append(skill_section)

    # ---- Layer 5: CITA 意图覆盖 ----
    if cita_overlay:
        cita_section = f"## 当前对话上下文\n{cita_overlay}"
        parts.insert(1, cita_section)  # 插入到用户画像之后、系统规则之前

    result = "\n\n---\n\n".join(parts)
    logger.info(
        f"[Composer] Prompt 组装完成: persona={'✓' if persona else '✗'}, "
        f"style={style or 'default'}, "
        f"总长={len(result)} 字符"
    )
    return result


# ==================== 便捷函数 ====================

def compose_base_prompt(skills_summary: str = "") -> str:
    """组装无角色模式的基础 Prompt（默认助手）。"""
    return compose_prompt(persona=None, skills_summary=skills_summary)


def compose_persona_prompt(
    persona_name: str,
    style: str = "default",
    skills_summary: str = "",
) -> str:
    """组装有角色模式的完整 Prompt。"""
    return compose_prompt(
        persona=persona_name,
        style=style,
        skills_summary=skills_summary,
    )


# ==================== 缓存清除 ====================

def clear_cache():
    """清除文件读取缓存（用于热加载场景）。"""
    _read_file.cache_clear()
    logger.info("[Composer] 缓存已清除")


# ==================== 自检 ====================

if __name__ == "__main__":
    # 测试无角色模式
    print("=" * 50, "无角色模式", "=" * 50)
    base = compose_base_prompt(skills_summary="[测试] Skill 列表...")
    print(base[:500])

    print("\n", "=" * 50, "Cyrene + lively", "=" * 50)
    persona = compose_persona_prompt("Cyrene", style="lively")
    print(persona[:500])

    print("\n", "=" * 50, "Ye Shunguang + healing", "=" * 50)
    persona2 = compose_persona_prompt("Ye Shunguang", style="healing")
    print(persona2[:500])
