"""
Prompt 动态组合器
=================
按 ``共享底座 + 角色灵魂 + 语气风格 + 世界观 + 系统规则 + 动态上下文`` 分层
组装最终的系统提示词。

目录结构
--------
- ``prompts/system/``        系统规则层（tools + safety + output），始终注入
- ``prompts/roles/_shared/`` 共享扮演底座、共享风格、共享世界观（跨角色知识）
- ``prompts/roles/{slug}/``  角色专属包：soul/（base + soul）、styles/、worldbook/

设计原则
--------
- **分层组装**: 每层独立文件，按需组合，避免巨型单文件
- **共享层回退**: 角色专属文件优先，缺失时回退到 ``_shared/`` 同名文件
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
import re
from pathlib import Path
from functools import lru_cache
from typing import Optional

from utils.logger_handler import logger

# ==================== 路径常量 ====================

_PROMPTS_DIR = Path(__file__).resolve().parent
_ROLES_DIR = _PROMPTS_DIR / "roles"
_SHARED_DIR = _ROLES_DIR / "_shared"
_SHARED_WORLDBOOK_DIR = _SHARED_DIR / "worldbook"
_SYSTEM_DIR = _PROMPTS_DIR / "system"

_ANIME_SOURCE_POLICY = """
## 动漫来源优先级

- 对需要联网核实的动漫问题，先调用 `search_anime`。
- `search_anime` 聚合 Bangumi、AniList、Jikan 和已采集的 YUC 季表缓存；回答时说明实际使用的来源，不要混用不同来源的评分口径。
- 若工具返回 `websearch_fallback_required: true`，必须继续调用 `web_search`，不得凭模型记忆补全事实。
""".strip()

_SEARCH_SOURCE_POLICY = """
## 小说与游戏资料来源
- 涉及最新、今天、当前、实时、公告、资讯、活动、章节或明确要求搜索时，禁止直接凭记忆回答，必须先调用对应工具；即使你认为自己知道答案，也必须以工具返回结果为准。
- 具体起点小说问题：先调用 `search_novel(keyword)` 获取前 N 条摘要；确定作品后再调用 `fetch_novel(book_url)` 获取详情。
- 小说搜索失败、结果为空或需要更广泛资料时，调用 `web_search` 兜底，不要凭记忆编造最新章节。
- 原神、崩坏：星穹铁道、绝区零的官方公告、资讯和活动：调用 `search_game_official(game, limit)`。
- 游戏抓取结果为空或提示 `websearch_fallback_required: true` 时，调用 `web_search` 兜底，并说明实际来源。
""".strip()

# 角色名 → 角色包目录名映射
_PERSONA_TO_SLUG: dict[str, str] = {
    "Cyrene":          "cyrene",
    "Columbina":       "columbina",
    "Ye Shunguang":    "ye-shunguang",
    "Zhuang Fangyi":   "zhuang-fangyi",
}

# 角色名 → 展示名（用于渲染 _shared/base.md 的 {{character_name}} 占位符）
_PERSONA_DISPLAY: dict[str, str] = {
    "Cyrene":          "昔涟",
    "Columbina":       "哥伦比娜",
    "Ye Shunguang":    "叶瞬光",
    "Zhuang Fangyi":   "庄芳怡",
}

# 风格名 → style 文件名映射（serious 为旧名，映射到 focused）
_STYLE_FILES: dict[str, str] = {
    "default":  "01_default.md",
    "lively":   "02_lively.md",
    "healing":  "03_healing.md",
    "focused":  "04_focused.md",
    "sweet":    "05_sweet.md",
    "serious":  "04_focused.md",
}

# 角色 worldbook 条目的元数据行（解析「常驻」条目用）
_RE_ENTRY_META = {
    "triggers": re.compile(r"^-\s*触发词[:：]\s*(.*)$"),
    "resident": re.compile(r"^-\s*常驻[:：]\s*(.*)$"),
    "meta_skip": re.compile(r"^-\s*(内在价值|优先级|连带触发词)[:：]\s*"),
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
    parts.append(_ANIME_SOURCE_POLICY)
    parts.append(_SEARCH_SOURCE_POLICY)
    return "\n\n---\n\n".join(parts) if parts else ""


def _render_shared_base(persona_name: str) -> str:
    """加载共享扮演底座并渲染角色名占位符。"""
    content = _read_file(_SHARED_DIR / "base.md")
    if not content:
        return ""
    display = _PERSONA_DISPLAY.get(persona_name, persona_name)
    return content.replace("{{character_name}}", display)


def _load_worldbook() -> str:
    """加载共享世界观知识（world + characters + glossary）。"""
    parts: list[str] = []
    for name in ("world", "characters", "glossary"):
        content = _read_file(_SHARED_WORLDBOOK_DIR / f"{name}.md")
        if content:
            parts.append(content)
    return "\n\n---\n\n".join(parts) if parts else ""


def _load_resident_entries(slug: str) -> str:
    """加载角色 worldbook 中的「常驻」条目（始终注入的部分）。"""
    wb_dir = _ROLES_DIR / slug / "worldbook"
    if not wb_dir.is_dir():
        return ""

    parts: list[str] = []
    for path in sorted(wb_dir.glob("*.md")):
        text = _read_file(path)
        if not text:
            continue
        for entry in _iter_entries(text):
            if entry["resident"]:
                parts.append(f"### {entry['title']}\n{entry['content']}")

    if not parts:
        return ""
    return "## 角色常驻设定（始终生效）\n" + "\n\n".join(parts)


def _iter_entries(text: str):
    """按 ``## 标题`` 切分 worldbook 文件，解析条目元数据（触发词/常驻）。"""
    chunks = re.split(r"^##\s+(.*?)$", text, flags=re.MULTILINE)
    # chunks[0] 为文件前言，之后每两段为 [标题, 正文]
    for i in range(1, len(chunks), 2):
        title = chunks[i].strip()
        body = chunks[i + 1] if (i + 1) < len(chunks) else ""
        triggers: list[str] = []
        resident = False
        content_lines: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            m = _RE_ENTRY_META["triggers"].match(stripped)
            if m:
                triggers = [t.strip() for t in re.split(r"[,，、]", m.group(1)) if t.strip()]
                continue
            m = _RE_ENTRY_META["resident"].match(stripped)
            if m:
                resident = m.group(1).strip() in ("是", "true", "True", "1", "常驻")
                continue
            if _RE_ENTRY_META["meta_skip"].match(stripped):
                continue
            content_lines.append(line)
        yield {
            "title": title,
            "triggers": triggers,
            "resident": resident,
            "content": "\n".join(content_lines).strip(),
        }


def _load_soul(persona_name: str) -> str:
    """加载角色灵魂层（共享底座 + base.md + soul.md）。

    Args:
        persona_name: 角色名（如 "Cyrene"、"Ye Shunguang"）。

    Returns:
        灵魂层内容；若角色不存在则返回空字符串。
    """
    slug = _PERSONA_TO_SLUG.get(persona_name)
    if not slug:
        logger.warning(f"[Composer] 未知角色: {persona_name}")
        return ""

    parts: list[str] = []

    # 1) 共享扮演底座（最先注入）
    shared_base = _render_shared_base(persona_name)
    if shared_base:
        parts.append(shared_base)

    # 2) 角色专属 soul 层（base 速览 + soul 细则）
    soul_dir = _ROLES_DIR / slug / "soul"
    for name in ("base.md", "soul.md"):
        content = _read_file(soul_dir / name)
        if content:
            parts.append(content)

    return "\n\n---\n\n".join(parts) if parts else ""


def _load_style(style_name: str, persona: Optional[str] = None) -> str:
    """加载语气风格文件，角色专属优先，回退到共享风格。

    Args:
        style_name: 风格名（default / lively / healing / focused / sweet）。
        persona:    角色名，用于定位角色专属风格目录。

    Returns:
        风格文件内容；若均不存在则返回空字符串。
    """
    filename = _STYLE_FILES.get(style_name, _STYLE_FILES["default"])

    # 1) 角色专属风格
    if persona:
        slug = _PERSONA_TO_SLUG.get(persona)
        if slug:
            content = _read_file(_ROLES_DIR / slug / "styles" / filename)
            if content:
                return content

    # 2) 共享同名风格
    content = _read_file(_SHARED_DIR / "styles" / filename)
    if content:
        return content

    # 3) 最终回退：共享默认风格
    return _read_file(_SHARED_DIR / "styles" / _STYLE_FILES["default"])


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
            style_content = _load_style(style_name, persona)
            if style_content:
                soul = f"{soul}\n\n---\n\n## 当前语气风格: {style_name}\n{style_content}"

            # 附上角色常驻设定
            slug = _PERSONA_TO_SLUG.get(persona, "")
            resident = _load_resident_entries(slug) if slug else ""
            if resident:
                soul = f"{soul}\n\n---\n\n{resident}"

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
