"""根据用户请求建立确定性的取证与工具约束。"""

from __future__ import annotations

import re

from .tool_contracts import ToolRequirement


_FRESH_WORDS = re.compile(r"今天|今日|明天|昨天|现在|当前|实时|最新|近期|刚刚|本周|本月")
_OFFICIAL_WORDS = re.compile(r"官方|官网|米游社|公告|资讯|活动")
_LINK_WORDS = re.compile(r"URL|链接|网址", re.IGNORECASE)
_WEATHER_WORDS = re.compile(r"天气|气温|温度|降雨|下雨|台风|湿度|风力")
_NEWS_WORDS = re.compile(r"新闻|资讯|公告|活动|更新|版本")
_SEARCH_WORDS = re.compile(r"搜索|检索|查询|查一下|帮我查|联网")
_PRICE_WORDS = re.compile(r"价格|股价|汇率|票价")
_GAME_WORDS = re.compile(r"原神|崩坏[:：]?星穹铁道|星穹铁道|绝区零|米游社")


class ToolPolicy:
    """P0 使用可审计规则；后续分类器只能补充，不能放宽规则。"""

    def evaluate(self, prompt: str, available_tools: set[str]) -> ToolRequirement:
        text = str(prompt or "").strip()
        freshness = bool(_FRESH_WORDS.search(text))
        official = bool(_OFFICIAL_WORDS.search(text))
        link_required = bool(_LINK_WORDS.search(text))
        weather = bool(_WEATHER_WORDS.search(text))
        news = bool(_NEWS_WORDS.search(text))
        explicit_search = bool(_SEARCH_WORDS.search(text))
        price = bool(_PRICE_WORDS.search(text))
        evidence_required = weather or price or explicit_search or link_required or (
            freshness and (news or official)
        )

        preferred: list[str] = []
        required_fields: tuple[str, ...] = ()
        if weather:
            preferred = self._existing(
                ("maps_weather", "maps_ip_location", "get_public_ip"),
                available_tools,
            )
            required_fields = ("weather",)
        elif official and _GAME_WORDS.search(text):
            preferred = self._existing(("search_game_official", "web_search"), available_tools)
            fields = ["title"]
            if link_required:
                fields.append("url")
            if freshness:
                fields.append("published_at")
            required_fields = tuple(fields)
        elif evidence_required:
            search_tools = sorted(name for name in available_tools if "search" in name)
            preferred = search_tools

        reason_parts = []
        if freshness:
            reason_parts.append("请求包含时效信息")
        if official:
            reason_parts.append("请求指定官方来源")
        if link_required:
            reason_parts.append("请求需要可验证链接")
        if weather:
            reason_parts.append("天气属于外部动态事实")
        if explicit_search:
            reason_parts.append("用户明确要求检索")

        return ToolRequirement(
            evidence_required=evidence_required,
            freshness_required=freshness,
            official_only=official,
            required_fields=required_fields,
            preferred_tools=tuple(preferred),
            allowed_tools=tuple(sorted(available_tools)),
            max_tool_calls=8,
            max_attempts_per_tool=2,
            allow_partial_answer=True,
            reason="；".join(reason_parts) or "普通知识请求",
        )

    @staticmethod
    def _existing(names: tuple[str, ...], available: set[str]) -> list[str]:
        return [name for name in names if name in available]


tool_policy = ToolPolicy()
