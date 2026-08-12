"""
Skill 注册表
===========
管理 Skill 的注册、查找、匹配、启用/禁用。
匹配策略：Slash Command 精确匹配 > 关键词匹配 > LLM 语义匹配（由调用方实现）
"""

import logging
import re
from typing import Optional

from .models import Skill, SkillMatch

logger = logging.getLogger("agent.skill_registry")


class SkillRegistry:
    """Skill 注册表（进程级单例）。"""

    def __init__(self):
        self._skills: dict[str, Skill] = {}   # name → Skill
        self._disabled: set[str] = set()       # 被禁用的 Skill name

    # ---- 注册 / 注销 ----

    def register(self, skill: Skill):
        """注册一个 Skill（同名覆盖）。"""
        self._skills[skill.name] = skill

    def register_all(self, skills: dict[str, Skill]):
        """批量注册。"""
        self._skills.update(skills)

    def unregister(self, name: str):
        """注销指定 Skill。"""
        self._skills.pop(name, None)
        self._disabled.discard(name)

    # ---- 查找 ----

    def get(self, name: str) -> Optional[Skill]:
        """按名称精确查找。"""
        return self._skills.get(name)

    def list_all(self, include_disabled: bool = False) -> list[Skill]:
        """列出全部 Skill（默认不含已禁用）。"""
        if include_disabled:
            return list(self._skills.values())
        return [s for s in self._skills.values() if s.name not in self._disabled]

    def list_by_category(self, category: str) -> list[Skill]:
        """按分类列出。"""
        return [s for s in self.list_all() if s.category == category]

    @property
    def count(self) -> int:
        return len(self.list_all())

    # ---- 启用 / 禁用 ----

    def enable(self, name: str):
        """启用 Skill。"""
        self._disabled.discard(name)

    def disable(self, name: str):
        """禁用 Skill。"""
        self._disabled.add(name)

    def is_enabled(self, name: str) -> bool:
        return name in self._skills and name not in self._disabled

    # ---- 匹配 ----

    def match(self, user_message: str, intent: Optional[str] = None) -> Optional[SkillMatch]:
        """根据用户消息和意图匹配最佳 Skill。

        匹配优先级：
        1. Slash Command 精确匹配（/skill-name）
        2. description 关键词匹配
        3. 按 priority 排序，分数最高的胜出

        Args:
            user_message: 用户消息原文
            intent: Decision Engine 输出的意图（可选，增强匹配）

        Returns:
            SkillMatch 或 None（无匹配时）
        """
        candidates: list[SkillMatch] = []

        # 1) Slash Command 精确匹配
        slash_name = _extract_slash_command(user_message)
        if slash_name:
            skill = self.get(slash_name)
            if skill and skill.name not in self._disabled:
                return SkillMatch(skill=skill, score=1.0, reason="slash_command")

        # 2) description 关键词匹配（对所有启用的 Skill）
        for skill in self.list_all():
            score = _keyword_match_score(user_message, skill)
            if score > 0:
                candidates.append(SkillMatch(skill=skill, score=score, reason="keyword_match"))

        # 按 priority × 匹配分数 排序
        candidates.sort(key=lambda m: m.skill.priority * m.score, reverse=True)

        if candidates and candidates[0].score >= 0.15:  # 最低阈值
            return candidates[0]

        return None

    def match_by_name(self, name: str) -> Optional[SkillMatch]:
        """按名称精确匹配（给 invoke_skill 工具调用）。"""
        skill = self.get(name)
        if skill and skill.name not in self._disabled:
            return SkillMatch(skill=skill, score=1.0, reason="exact_name")
        return None

    # ---- 摘要生成 ----

    def build_skills_summary(self) -> str:
        """生成可用 Skill 的摘要文本（注入 Agent system prompt）。"""
        skills = self.list_all()
        if not skills:
            return "（无可用 Skill）"

        lines = []
        for skill in sorted(skills, key=lambda s: s.category):
            lines.append(f"- {skill.emoji} **{skill.name}** [{skill.category}]: {skill.description[:80]}")
        return "\n".join(lines)

    def clear(self):
        """清空注册表（用于测试）。"""
        self._skills.clear()
        self._disabled.clear()


# ==================== 匹配辅助函数 ====================

def _extract_slash_command(text: str) -> Optional[str]:
    """从消息中提取 Slash Command（如 /recommend_anime）。"""
    m = re.match(r"^\s*/(\S+)", text)
    if m:
        return m.group(1).strip()
    return None


def _extract_cn_ngrams(text: str, min_len: int = 2, max_len: int = 4) -> set[str]:
    """从文本中提取中文 n-gram（滑动窗口），用作匹配关键词。"""
    # 先提取所有连续中文片段
    segments = re.findall(r"[一-鿿]+", text)
    ngrams: set[str] = set()
    for seg in segments:
        for n in range(min_len, max_len + 1):
            for i in range(len(seg) - n + 1):
                ngrams.add(seg[i:i + n])
    return ngrams


def _keyword_match_score(user_message: str, skill: Skill) -> float:
    """基于 description 的匹配分数。

    核心思路：用户消息中的 n-gram 有多少命中 description（加权覆盖）。
    短中文消息 n-gram 数量多（跨词边界噪声），因此：
    - 评分乘数基数设为 1.0（而非 <1.0），避免过度惩罚短消息
    - 长描述有轻微折扣（越长越容易误匹配）
    - Skill name 命中提供额外加成
    """
    desc_lower = skill.description.lower()
    msg_lower = user_message.lower()

    # 用户消息的 n-gram
    msg_ngrams = _extract_cn_ngrams(msg_lower, min_len=2, max_len=3)
    msg_en_words = {w for w in re.findall(r"[a-zA-Z]{3,}", msg_lower)}
    msg_keywords = msg_ngrams | msg_en_words

    if not msg_keywords:
        return 0.0

    # 描述中出现的用户 n-gram 有多少命中
    matched = {kw for kw in msg_keywords if kw in desc_lower}
    if not matched:
        return 0.0

    # 加权：2 字权重 0.5，3 字及以上权重 1.0
    matched_weight = sum(0.5 if len(kw) <= 2 else 1.0 for kw in matched)
    total_weight = sum(0.5 if len(kw) <= 2 else 1.0 for kw in msg_keywords)
    coverage = matched_weight / total_weight if total_weight > 0 else 0

    # 长描述折扣（描述越长命中越容易，需小幅打折）
    desc_len_bonus = min(1.0, 80 / max(len(desc_lower), 1))
    score = coverage * (1.0 + 0.5 * desc_len_bonus)

    # ---- Skill name 关键词加成 ----
    # 如果用户消息包含 skill name 中的 n-gram，额外加分
    name_lower = skill.name.lower()
    name_ngrams = _extract_cn_ngrams(name_lower, min_len=2, max_len=3)
    name_matches = sum(
        0.5 if len(kw) <= 2 else 1.0
        for kw in msg_keywords if kw in name_lower
    )
    if name_matches > 0:
        score += name_matches * 0.08  # 每个 name 命中 +0.04~0.08

    return min(score, 1.0)


# ==================== 进程级单例 ====================

_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取 Skill 注册表单例。"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
