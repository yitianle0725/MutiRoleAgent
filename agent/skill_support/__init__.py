"""
Skill 支持框架
=============
提供 Skill 的加载、注册、匹配和调用能力。

设计参考：
- EchoBot 的 echobot/skill_support/ 框架结构
- Claude Code 的 SKILL.md YAML frontmatter 格式

用法：
    from agent.skill_support import init_skills, get_skill_registry

    # 异步初始化（应用启动时调用一次，避免阻塞事件循环）
    await init_skills()

    # 获取注册表
    registry = get_skill_registry()

    # 匹配 Skill
    match = registry.match(user_message="推荐几部热血番", intent="recommendation")
    if match:
        print(match.skill.name, match.score, match.reason)
"""

import asyncio
import logging

from .models import Skill, SkillMatch, SkillInvocation
from .loader import load_all_skills, reload_skill
from .registry import SkillRegistry, get_skill_registry
from .tools import SKILL_TOOLS, list_skills, invoke_skill

logger = logging.getLogger("agent.skill_support")


async def init_skills() -> SkillRegistry:
    """初始化 Skill 系统：加载全部 Skill 并注册（异步，避免阻塞事件循环）。

    在应用启动时调用一次。文件扫描通过 asyncio.to_thread 转移到后台线程执行。
    返回全局注册表。
    """
    registry = get_skill_registry()
    # 磁盘 I/O 通过 asyncio.to_thread 转移，不阻塞事件循环（遵循 AGENTS.md 异步规范）
    skills = await asyncio.to_thread(load_all_skills)
    registry.register_all(skills)
    logger.info(f"Skill 系统初始化完成: {registry.count} 个 Skill 已注册")
    return registry


__all__ = [
    "Skill",
    "SkillMatch",
    "SkillInvocation",
    "load_all_skills",
    "reload_skill",
    "SkillRegistry",
    "get_skill_registry",
    "init_skills",
    "SKILL_TOOLS",
    "list_skills",
    "invoke_skill",
]
