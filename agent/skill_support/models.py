"""
Skill 数据模型
=============
Skill 对象、SkillMatch 匹配结果等核心数据结构。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Skill:
    """一个 Skill 实例，对应一个包含 SKILL.md 的目录。

    元数据来自 SKILL.md 的 YAML frontmatter，
    正文 content 是 Agent 可阅读的自然语言指令。
    """

    name: str                              # Skill 唯一标识（目录名，或 frontmatter 中的 name）
    path: Path                             # Skill 目录的绝对路径
    description: str = ""                  # 一句话描述（用于关键词匹配 + Agent 理解）
    content: str = ""                      # SKILL.md 正文（注入 Agent 上下文）
    emoji: str = "📋"                      # 前端展示图标
    category: str = "utility"             # 分类：anime / utility / file / life
    priority: int = 5                      # 优先级 1-10（匹配冲突时）
    homepage: str = ""                     # 外部参考链接
    source: str = "builtin"               # "builtin" | "user"
    enabled: bool = True
    output_schema: str = ""                # Phase 6: SCHEMA_REGISTRY 键名（如 "anime_recommendation"）
    references: list[Path] = field(default_factory=list)  # references/ 下的文档
    scripts: list[Path] = field(default_factory=list)     # scripts/ 下的可执行文件

    def read_reference(self, ref_path: Path) -> str:
        """读取 references/ 下的参考文档内容。"""
        try:
            return ref_path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def all_references_text(self) -> str:
        """读取所有参考文档，拼接为一个字符串注入上下文。"""
        texts = []
        for rp in self.references:
            content = self.read_reference(rp)
            if content:
                texts.append(f"--- {rp.name} ---\n{content}")
        return "\n\n".join(texts)


@dataclass
class SkillMatch:
    """Skill 匹配结果。"""

    skill: Skill
    score: float                           # 匹配分数 0-1
    reason: str = ""                       # 匹配原因（"slash_command" / "keyword" / "llm_semantic"）


@dataclass
class SkillInvocation:
    """记录一次 Skill 调用。"""

    skill_name: str
    task: str                              # 用户任务描述
    trace_id: str = ""
    success: bool = False
    summary: str = ""                      # 执行结果摘要
