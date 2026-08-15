"""
世界观知识检索器
================
从 worldbook 中按需检索相关世界观知识，避免全量注入浪费 Token。

数据源
------
- **共享层**: ``prompts/roles/_shared/worldbook/{world,characters,glossary}.md``
  跨角色知识（助手世界观、四位助手、动漫术语），按 ## 标题分节。
- **角色层**: ``prompts/roles/{slug}/worldbook/*.md``
  角色专属条目，每条含元数据（触发词/常驻/内在价值/优先级/连带触发词）。

检索策略
--------
- **角色关联**：当前角色的「常驻」条目自动包含
- **关键词匹配**：对用户查询匹配共享层索引与角色条目「触发词」
- **实体触发**：CITA 提取的实体触发相关条目

与 composer.py 的 _load_worldbook() 区别：
- composer 始终加载共享层 3 个文件 + 角色常驻条目
- retriever 仅返回**相关的片段**（通常 < 500 字符/条）

使用方式::

    from agent.persona.worldbook_retriever import WorldbookRetriever

    retriever = WorldbookRetriever()
    entries = retriever.retrieve(
        query="Cyrene 是什么角色？",
        persona="Cyrene",
        entities=[Entity(type="character", value="昔涟")],
    )
    # → 返回角色常驻条目 + 匹配触发词/关键词的条目
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
_WB_CFG = _PERSONA_CFG.get("worldbook", {})
_CHAR_CFG = _PERSONA_CFG.get("characters", {})

# 路径
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_ROLES_DIR = _PROMPTS_DIR / "roles"
_SHARED_WB_DIR = _ROLES_DIR / "_shared" / "worldbook"

# 角色 worldbook 条目的元数据行
_RE_ENTRY_META = {
    "triggers": re.compile(r"^-\s*触发词[:：]\s*(.*)$"),
    "resident": re.compile(r"^-\s*常驻[:：]\s*(.*)$"),
    "value":    re.compile(r"^-\s*内在价值[:：]\s*(.*)$"),
    "priority": re.compile(r"^-\s*优先级[:：]\s*(.*)$"),
    "chain":    re.compile(r"^-\s*连带触发词[:：]\s*(.*)$"),
}


def _slug_of(persona: str) -> str:
    """解析角色包目录名。"""
    char_cfg = _CHAR_CFG.get(persona, {})
    slug = char_cfg.get("slug", "")
    if slug:
        return slug
    from prompts.composer import _PERSONA_TO_SLUG
    return _PERSONA_TO_SLUG.get(persona, "")


# ==================== 数据结构 ====================

@dataclass
class WorldbookEntry:
    """世界观知识条目。"""
    source: str                     # 来源（共享文件名或 "{slug}:{文件名}"）
    title: str                      # 条目标题
    content: str                    # 条目内容
    relevance_score: float = 0.0    # 相关性评分
    match_keywords: list[str] = field(default_factory=list)


# ==================== 共享层关键词索引 ====================

# 共享 worldbook 索引（文件名 → {节标题: 关键词}）
_DEFAULT_KEYWORD_INDEX: dict[str, dict[str, list[str]]] = {
    "world": {
        "项目定位": ["项目", "定位", "MutiRoleAgent", "多角色"],
        "角色来源": ["来源", "作品", "原作", "崩坏", "原神", "绝区零", "明日方舟", "Honkai", "Genshin", "Zenless", "Arknights"],
        "助手世界观": ["世界观", "跨次元", "助手空间", "空间规则", "核心使命", "角色扮演"],
    },
    "characters": {
        "四位助手": ["Cyrene", "昔涟", "Columbina", "哥伦比娜", "叶瞬光", "瞬光", "庄方宜", "庄芳怡", "方宜", "粉红", "妖精", "月神", "狐族", "剑士", "麒麟", "行政官", "角色介绍", "角色信息"],
        "角色间关系": ["关系", "亲近", "同事", "互动", "角色关系"],
    },
    "glossary": {
        "动漫相关": ["新番", "番剧", "季度", "bangumi", "评分", "排名", "季番", "年番", "剧场版", "OVA", "声优", "制作公司", "轻改", "漫改", "原创"],
    },
}


class WorldbookRetriever:
    """世界观知识检索器。

    按相关性从共享层 + 角色层 worldbook 中检索相关条目，
    仅注入相关的知识片段而非全量 worldbook。

    使用示例::

        retriever = WorldbookRetriever()
        entries = retriever.retrieve(
            query="推荐几部热血番",
            persona="Ye Shunguang",
        )
        # → 自动包含叶瞬光常驻条目（角色关联）+ 番剧术语条目
    """

    def __init__(self):
        self._shared_wb_dir = _SHARED_WB_DIR
        self._max_entries = _WB_CFG.get("max_entries", 5)
        self._max_entry_chars = _WB_CFG.get("max_entry_chars", 500)
        self._keyword_index = _DEFAULT_KEYWORD_INDEX  # 使用内置索引
        # 缓存：共享 worldbook 文件分节 & 角色 worldbook 条目
        self._parsed_cache: dict[str, dict[str, str]] = {}
        self._persona_cache: dict[str, list[dict]] = {}

    # ==================== 检索主入口 ====================

    def retrieve(
        self,
        query: str = "",
        persona: str | None = None,
        entities: list | None = None,
        topic: str | None = None,
        max_entries: int | None = None,
    ) -> list[WorldbookEntry]:
        """检索相关的世界观知识条目。

        Args:
            query: 用户查询文本。
            persona: 当前角色名（角色关联的条目自动包含）。
            entities: CITA 提取的实体列表。
            topic: 检测到的话题标签。
            max_entries: 最大返回条目数。

        Returns:
            按相关性降序排列的 WorldbookEntry 列表。
        """
        max_entries = max_entries or self._max_entries
        entries: list[WorldbookEntry] = []

        # 1) 角色关联（最高优先级）
        if persona:
            char_entries = self._retrieve_by_character(persona)
            entries.extend(char_entries)

        # 2) 实体匹配
        if entities:
            entity_entries = self._retrieve_by_entities(entities, persona)
            entries.extend(entity_entries)

        # 3) 查询关键词匹配
        if query:
            query_entries = self._retrieve_by_query(query, persona)
            entries.extend(query_entries)

        # 4) 话题匹配
        if topic:
            topic_entries = self._retrieve_by_topic(topic)
            entries.extend(topic_entries)

        # 去重 + 排序 + 截断
        entries = self._deduplicate(entries)
        entries.sort(key=lambda e: e.relevance_score, reverse=True)
        entries = entries[:max_entries]

        # 截断过长内容
        for entry in entries:
            if len(entry.content) > self._max_entry_chars:
                entry.content = entry.content[:self._max_entry_chars] + "…"

        logger.debug(
            f"[WorldbookRetriever] 检索: query={query[:30] if query else 'N/A'}, "
            f"persona={persona}, entries={len(entries)}"
        )
        return entries

    # ==================== 各检索方法 ====================

    def _retrieve_by_character(self, persona: str) -> list[WorldbookEntry]:
        """检索角色关联的世界观条目（常驻条目 + 触发词含角色名的条目）。"""
        entries: list[WorldbookEntry] = []
        slug = _slug_of(persona)
        if not slug:
            return entries

        name_tokens = {persona.lower(), slug.lower()}
        display = _CHAR_CFG.get(persona, {}).get("display_name", "")
        if display:
            name_tokens.add(display.lower())

        for raw in self._load_persona_entries(slug):
            if raw["resident"]:
                entries.append(WorldbookEntry(
                    source=raw["source"],
                    title=raw["title"],
                    content=raw["content"],
                    relevance_score=0.9,
                    match_keywords=["常驻"],
                ))
            elif any(tok in " ".join(raw["triggers"]).lower() for tok in name_tokens):
                entries.append(WorldbookEntry(
                    source=raw["source"],
                    title=raw["title"],
                    content=raw["content"],
                    relevance_score=0.5,
                    match_keywords=[persona],
                ))

        # 自动包含共享层"角色间关系"条目
        char_sections = self._load_file_sections("characters")
        if "角色间关系" in char_sections:
            entries.append(WorldbookEntry(
                source="characters",
                title="角色间关系",
                content=char_sections["角色间关系"],
                relevance_score=0.5,
                match_keywords=["角色关系"],
            ))

        return entries

    def _retrieve_by_entities(
        self, entities: list, persona: str | None = None
    ) -> list[WorldbookEntry]:
        """检索实体关联的世界观条目。"""
        entries: list[WorldbookEntry] = []
        entity_values = [
            e.value if hasattr(e, 'value') else str(e)
            for e in entities
        ]

        # 共享层
        for source_name in ["characters", "glossary", "world"]:
            sections = self._load_file_sections(source_name)
            for title, content in sections.items():
                matched = [ev for ev in entity_values if ev in title or ev in content]
                if matched:
                    entries.append(WorldbookEntry(
                        source=source_name,
                        title=title,
                        content=content,
                        relevance_score=0.7,
                        match_keywords=matched,
                    ))

        # 角色层
        if persona:
            slug = _slug_of(persona)
            if slug:
                for raw in self._load_persona_entries(slug):
                    haystack = raw["title"] + raw["content"] + " ".join(raw["triggers"])
                    matched = [ev for ev in entity_values if ev in haystack]
                    if matched:
                        entries.append(WorldbookEntry(
                            source=raw["source"],
                            title=raw["title"],
                            content=raw["content"],
                            relevance_score=0.7,
                            match_keywords=matched,
                        ))

        return entries

    def _retrieve_by_query(
        self, query: str, persona: str | None = None
    ) -> list[WorldbookEntry]:
        """通过查询关键词匹配检索条目（共享层索引 + 角色条目触发词）。"""
        entries: list[WorldbookEntry] = []

        # 共享层关键词索引
        for source_name, sections_idx in self._keyword_index.items():
            sections = self._load_file_sections(source_name)
            for section_title, keywords in sections_idx.items():
                matched = [kw for kw in keywords if kw in query]
                if matched:
                    content = sections.get(section_title, "")
                    if content:
                        entries.append(WorldbookEntry(
                            source=source_name,
                            title=section_title,
                            content=content,
                            relevance_score=0.5 + 0.1 * len(matched),
                            match_keywords=matched,
                        ))

        # 角色层触发词匹配
        if persona:
            slug = _slug_of(persona)
            if slug:
                for raw in self._load_persona_entries(slug):
                    matched = [kw for kw in raw["triggers"] if kw and kw in query]
                    if matched:
                        entries.append(WorldbookEntry(
                            source=raw["source"],
                            title=raw["title"],
                            content=raw["content"],
                            relevance_score=0.55 + 0.1 * len(matched),
                            match_keywords=matched,
                        ))

        return entries

    def _retrieve_by_topic(self, topic: str) -> list[WorldbookEntry]:
        """通过话题标签检索共享层条目。"""
        entries: list[WorldbookEntry] = []

        # 话题 → worldbook 映射
        topic_map = {
            "anime_recommend": ("glossary", ["动漫相关"]),
            "anime_analysis": ("glossary", ["动漫相关"]),
            "emotional_support": ("characters", ["角色间关系"]),
            "casual_chat": ("world", ["助手世界观"]),
        }

        if topic in topic_map:
            source_name, section_titles = topic_map[topic]
            sections = self._load_file_sections(source_name)
            for title in section_titles:
                content = sections.get(title, "")
                if content:
                    entries.append(WorldbookEntry(
                        source=source_name,
                        title=title,
                        content=content,
                        relevance_score=0.4,
                        match_keywords=[topic],
                    ))

        return entries

    # ==================== 文件加载 ====================

    def _load_file_sections(self, name: str) -> dict[str, str]:
        """加载共享层 worldbook 文件并按 ## 标题拆分为段落。"""
        if name in self._parsed_cache:
            return self._parsed_cache[name]

        filepath = self._shared_wb_dir / f"{name}.md"
        if not filepath.exists():
            logger.debug(f"[WorldbookRetriever] 文件不存在: {filepath}")
            return {}

        try:
            text = filepath.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"[WorldbookRetriever] 读取失败: {filepath} — {e}")
            return {}

        sections = self._split_sections(text)
        self._parsed_cache[name] = sections
        return sections

    def _load_persona_entries(self, slug: str) -> list[dict]:
        """加载角色 worldbook 全部条目（解析元数据，带缓存）。"""
        if slug in self._persona_cache:
            return self._persona_cache[slug]

        wb_dir = _ROLES_DIR / slug / "worldbook"
        entries: list[dict] = []
        if not wb_dir.is_dir():
            logger.debug(f"[WorldbookRetriever] 角色 worldbook 目录不存在: {wb_dir}")
            self._persona_cache[slug] = entries
            return entries

        for path in sorted(wb_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(f"[WorldbookRetriever] 读取失败: {path} — {e}")
                continue
            entries.extend(self._parse_entries(text, f"{slug}:{path.stem}"))

        logger.debug(
            f"[WorldbookRetriever] 已加载角色 worldbook: {slug} "
            f"({len(entries)} 条)"
        )
        self._persona_cache[slug] = entries
        return entries

    def _parse_entries(self, text: str, source: str) -> list[dict]:
        """按 ``## 标题`` 切分文件，解析条目元数据（触发词/常驻/优先级等）。"""
        chunks = re.split(r"^##\s+(.*?)$", text, flags=re.MULTILINE)
        entries: list[dict] = []
        # chunks[0] 为文件前言，之后每两段为 [标题, 正文]
        for i in range(1, len(chunks), 2):
            title = chunks[i].strip()
            body = chunks[i + 1] if (i + 1) < len(chunks) else ""
            triggers: list[str] = []
            resident = False
            priority = 0
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
                m = _RE_ENTRY_META["value"].match(stripped)
                if m:
                    continue  # 内在价值仅作标注，不参与检索评分
                m = _RE_ENTRY_META["priority"].match(stripped)
                if m:
                    try:
                        priority = int(m.group(1).strip())
                    except ValueError:
                        pass
                    continue
                m = _RE_ENTRY_META["chain"].match(stripped)
                if m:
                    continue  # 连带触发词暂不参与检索
                content_lines.append(line)
            entries.append({
                "source": source,
                "title": title,
                "triggers": triggers,
                "resident": resident,
                "priority": priority,
                "content": "\n".join(content_lines).strip(),
            })
        return entries

    @staticmethod
    def _split_sections(text: str) -> dict[str, str]:
        """按 ## 标题拆分 Markdown 文本为段落字典。"""
        sections: dict[str, str] = {}
        pattern = re.compile(r'^##\s+(.*?)$', re.MULTILINE)
        splits = pattern.split(text)

        if len(splits) <= 1:
            sections["_full"] = text
        else:
            preamble = splits[0].strip()
            if preamble:
                sections["_preamble"] = preamble
            for i in range(1, len(splits), 2):
                title = splits[i].strip()
                body = splits[i + 1].strip() if (i + 1) < len(splits) else ""
                sections[title] = body
            sections["_full"] = text

        return sections

    # ==================== 格式化 ====================

    def format_entries(self, entries: list[WorldbookEntry]) -> str:
        """将检索到的条目格式化为可注入 Prompt 的文本。

        Args:
            entries: 检索结果列表。

        Returns:
            格式化的世界观知识文本。
        """
        if not entries:
            return ""

        lines = ["## 相关世界观知识（按需注入）"]
        for entry in entries:
            lines.append(f"### {entry.title}")
            lines.append(entry.content)
            lines.append("")

        return "\n".join(lines)

    def format_compact(self, entries: list[WorldbookEntry]) -> str:
        """紧凑格式（适合 Token 紧张时）。"""
        if not entries:
            return ""

        parts = []
        for entry in entries:
            parts.append(f"【{entry.title}】{entry.content[:200]}")
        return " | ".join(parts)

    # ==================== 去重 ====================

    def _deduplicate(self, entries: list[WorldbookEntry]) -> list[WorldbookEntry]:
        """去重（按 source + title 去重，保留最高分）。"""
        seen: dict[tuple[str, str], WorldbookEntry] = {}
        for entry in entries:
            key = (entry.source, entry.title)
            if key not in seen or entry.relevance_score > seen[key].relevance_score:
                seen[key] = entry
        return list(seen.values())

    # ==================== 缓存管理 ====================

    def clear_cache(self):
        """清除已解析的文件缓存。"""
        self._parsed_cache.clear()
        self._persona_cache.clear()
        logger.info("[WorldbookRetriever] 缓存已清除")


# ==================== 模块级实例 ====================

worldbook_retriever = WorldbookRetriever()


# ==================== 便捷函数 ====================

def retrieve_worldbook(
    query: str = "",
    persona: str | None = None,
    entities: list | None = None,
) -> str:
    """快速检索世界观知识的便捷函数。

    Returns:
        可直接注入 prompt 的格式化文本。
    """
    entries = worldbook_retriever.retrieve(
        query=query, persona=persona, entities=entities,
    )
    return worldbook_retriever.format_entries(entries)


# ==================== 测试 ====================

if __name__ == "__main__":
    retriever = WorldbookRetriever()

    test_cases = [
        ("推荐几部热血番", "Ye Shunguang", None),
        ("Cyrene 是什么角色？", "Cyrene", None),
        ("什么是新番？怎么看评分？", None, None),
        ("心情不好想看点治愈的", "Columbina", None),
        ("介绍一下世界观", None, None),
    ]

    for query, persona, entities in test_cases:
        print(f"\n{'='*60}")
        print(f"Query: {query}, Persona: {persona}")
        entries = retriever.retrieve(query=query, persona=persona, entities=entities)
        for e in entries:
            print(f"  [{e.source}] {e.title} (score={e.relevance_score:.2f}) — {e.content[:80]}...")

    print(f"\n格式化输出:")
    entries = retriever.retrieve(query="推荐几部热血番", persona="Ye Shunguang")
    print(retriever.format_entries(entries)[:500])
