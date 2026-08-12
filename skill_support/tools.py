"""
Skill 工具
=========
暴露给 Agent 的 invoke_skill 和 list_skills 工具。
Agent 通过 Function Calling 调用这些工具来使用 Skill 系统。
"""

import logging
from typing import Optional

from langchain_core.tools import tool

from .registry import get_skill_registry

logger = logging.getLogger("agent.skill_tools")


@tool
def list_skills(category: Optional[str] = None) -> str:
    """列出所有可用的 Skill。

    当你不确定有哪些 Skill 可用、或用户问"你能做什么"时调用此工具。
    返回每个 Skill 的名称、描述和图标。

    Args:
        category: 可选，按分类筛选。可选值: anime / utility / file / life。
                  不传则列出全部。
    """
    registry = get_skill_registry()
    if category:
        skills = registry.list_by_category(category)
    else:
        skills = registry.list_all()

    if not skills:
        return "（暂无可用 Skill）"

    lines = [f"共 {len(skills)} 个可用 Skill：\n"]
    for s in sorted(skills, key=lambda x: (x.category, x.name)):
        lines.append(f"{s.emoji} **{s.name}** [{s.category}] (优先级:{s.priority})")
        if s.description:
            lines.append(f"   {s.description.strip()[:120]}")
        lines.append("")
    return "\n".join(lines)


@tool
def invoke_skill(skill_name: str, task: str = "") -> str:
    """激活并读取指定 Skill 的完整指令。

    调用后你会收到该 Skill 的 SKILL.md 正文 + references/ 参考文档，
    请严格按照其中的步骤执行任务。

    Args:
        skill_name: Skill 名称（精确匹配，如 "recommend_anime"、
                    "season_overview"、"weather_lifestyle" 等）。
                    先用 list_skills 确认名称。
        task: 用户的具体任务描述（可选），传入后可帮助 Skill 理解上下文。
    """
    registry = get_skill_registry()
    match = registry.match_by_name(skill_name)

    if match is None:
        available = [s.name for s in registry.list_all()]
        return (
            f"❌ Skill '{skill_name}' 不存在或已被禁用。\n"
            f"可用 Skill: {', '.join(available)}\n"
            f"请用 list_skills 查看完整列表后重试。"
        )

    skill = match.skill
    parts = [
        f"✅ 已激活 Skill: {skill.emoji} **{skill.name}**\n",
        f"--- SKILL.md ---",
        skill.content,
    ]

    # 注入 references/ 参考文档
    refs_text = skill.all_references_text()
    if refs_text:
        parts.append(f"\n--- 参考文档 (references/) ---")
        parts.append(refs_text)

    # 如果有 scripts/，告知 Agent 可执行
    if skill.scripts:
        parts.append(f"\n--- 可执行脚本 (scripts/) ---")
        for sp in skill.scripts:
            parts.append(f"- {sp.relative_to(skill.path)}")

    parts.append(f"\n--- 用户任务 ---\n{task}" if task else "")
    parts.append("\n请严格按照上述 Skill 指令执行任务，数据必须来自工具返回结果。")

    return "\n".join(parts)


# ---- 导出列表（注册到 Agent 的工具列表） ----

SKILL_TOOLS = [list_skills, invoke_skill]
