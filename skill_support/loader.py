"""
Skill 加载器
===========
扫描 skills/ 和 data/skills/ 目录，解析 SKILL.md 的 YAML frontmatter + Markdown 正文。

加载优先级：
1. data/skills/（用户自定义，同名覆盖内置）
2. skills/（内置，随项目发布）
"""

import logging
from pathlib import Path
from typing import Optional

import yaml

from .models import Skill

logger = logging.getLogger("agent.skill_loader")

# 项目根目录（agent/skill_support/loader.py → 上两级 = MutiRoleAgent/）
# ⚠️ 之前用了 .parent.parent.parent，多算了一层，导致 BUILTIN_SKILLS_DIR 指向
# 项目外的 D:/develop/PythonStudy/skills，整个 skills/ 加载为空。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

BUILTIN_SKILLS_DIR = _PROJECT_ROOT / "skills"
USER_SKILLS_DIR = _PROJECT_ROOT / "data" / "skills"

# SKILL.md 最多读取的字符数（防止过大文件撑爆上下文）
MAX_SKILL_MD_SIZE = 50_000


# 名称 → emoji / category 推断表（用于官方格式中未指定 metadata 的 Skill）
_NAME_EMOJI_MAP = {
    "pdf": "📄", "pptx": "📊", "xlsx": "📈", "docx": "📝",
    "skill-creator": "🛠️", "mcp-builder": "🔌",
}
_NAME_CATEGORY_MAP = {
    "pdf": "document", "pptx": "document", "xlsx": "document", "docx": "document",
    "skill-creator": "meta", "mcp-builder": "dev",
}


def _infer_emoji(name: str) -> str:
    """根据 Skill 名称推断合适的 emoji（官方 Skill 的兜底方案）。"""
    return _NAME_EMOJI_MAP.get(name, "📋")


def _infer_category(name: str) -> str:
    """根据 Skill 名称推断分类。"""
    return _NAME_CATEGORY_MAP.get(name, "utility")


def parse_skill_md(filepath: Path) -> dict:
    """解析 SKILL.md 的 YAML frontmatter + Markdown 正文。

    Args:
        filepath: SKILL.md 的绝对路径

    Returns:
        {"name": str, "description": str, "emoji": str, "category": str,
         "priority": int, "homepage": str, "content": str}
    """
    text = filepath.read_text(encoding="utf-8")[:MAX_SKILL_MD_SIZE]
    frontmatter = {}
    body = text

    # 提取 YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError as e:
                logger.warning(f"解析 {filepath} 的 frontmatter 失败: {e}")
            body = parts[2].strip()

    # 从 frontmatter 提取元数据（优先级：metadata 子字段 > 顶层字段 > 名称推断）
    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    name = frontmatter.get("name", filepath.parent.name)
    emoji = metadata.get("emoji") or frontmatter.get("emoji") or _infer_emoji(name)
    category = metadata.get("category") or frontmatter.get("category") or _infer_category(name)
    priority = int(metadata.get("priority") or frontmatter.get("priority") or 5)
    # Phase 6: 结构化输出 Schema
    output_schema = metadata.get("output_schema") or frontmatter.get("output_schema") or ""

    return {
        "name": name,
        "description": frontmatter.get("description", ""),
        "emoji": emoji,
        "category": category,
        "priority": priority,
        "homepage": frontmatter.get("homepage", ""),
        "output_schema": output_schema,
        "content": body,
    }


def scan_skill_dir(root: Path, source: str) -> list[Skill]:
    """扫描目录下所有含有 SKILL.md 的子目录，解析为 Skill 对象列表。

    Args:
        root: 扫描根目录
        source: "builtin" 或 "user"

    Returns:
        Skill 列表（SKILL.md 不存在或解析失败时跳过）
    """
    if not root.exists():
        return []

    skills: list[Skill] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        try:
            meta = parse_skill_md(skill_md)
        except Exception as e:
            logger.warning(f"跳过 {skill_md}: {e}")
            continue

        # 收集 references/ 下的文档
        refs_dir = skill_dir / "references"
        references = (
            sorted(refs_dir.rglob("*.md")) if refs_dir.exists() else []
        )

        # 收集 scripts/ 下的可执行文件
        scripts_dir = skill_dir / "scripts"
        scripts = (
            sorted(p for p in scripts_dir.rglob("*") if p.is_file())
            if scripts_dir.exists() else []
        )

        skill = Skill(
            name=meta["name"],
            path=skill_dir,
            description=meta["description"],
            content=meta["content"],
            emoji=meta["emoji"],
            category=meta["category"],
            priority=meta["priority"],
            homepage=meta["homepage"],
            output_schema=meta.get("output_schema", ""),
            source=source,
            references=references,
            scripts=scripts,
        )
        skills.append(skill)
        logger.debug(f"加载 Skill: {skill.name} ({source}, {len(references)} refs, {len(scripts)} scripts)")

    return skills


def load_all_skills() -> dict[str, Skill]:
    """加载全部 Skill（用户优先覆盖内置同名）。

    Returns:
        {skill_name: Skill} 字典，key 为 skill.name
    """
    # 先加载内置，再加载用户（后者覆盖前者）
    all_skills: dict[str, Skill] = {}

    for skill in scan_skill_dir(BUILTIN_SKILLS_DIR, "builtin"):
        all_skills[skill.name] = skill

    for skill in scan_skill_dir(USER_SKILLS_DIR, "user"):
        if skill.name in all_skills:
            logger.info(f"用户 Skill '{skill.name}' 覆盖内置版本")
        all_skills[skill.name] = skill

    logger.info(f"共加载 {len(all_skills)} 个 Skill "
                 f"(内置: {sum(1 for s in all_skills.values() if s.source == 'builtin')}, "
                 f"用户: {sum(1 for s in all_skills.values() if s.source == 'user')})")
    return all_skills


def reload_skill(name: str) -> Optional[Skill]:
    """热重载单个 Skill（文件变更后调用）。

    先检查 data/skills/（用户），再检查 skills/（内置）。
    """
    for root, source in [(USER_SKILLS_DIR, "user"), (BUILTIN_SKILLS_DIR, "builtin")]:
        skill_md = root / name / "SKILL.md"
        if skill_md.exists():
            try:
                meta = parse_skill_md(skill_md)
            except Exception:
                return None
            refs_dir = skill_md.parent / "references"
            scripts_dir = skill_md.parent / "scripts"
            return Skill(
                name=meta["name"],
                path=skill_md.parent,
                description=meta["description"],
                content=meta["content"],
                emoji=meta["emoji"],
                category=meta["category"],
                priority=meta["priority"],
                homepage=meta["homepage"],
                output_schema=meta.get("output_schema", ""),
                source=source,
                references=sorted(refs_dir.rglob("*.md")) if refs_dir.exists() else [],
                scripts=sorted(p for p in scripts_dir.rglob("*") if p.is_file()) if scripts_dir.exists() else [],
            )
    return None
