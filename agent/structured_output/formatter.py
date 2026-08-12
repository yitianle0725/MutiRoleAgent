"""
格式化渲染器
============
将校验通过的 Pydantic 模型转换为丰富的 Markdown 文本，
适合 Streamlit 的 ``st.write()`` 渲染。

每种 Schema 对应一个 formatter 函数。
"""

from __future__ import annotations

from pydantic import BaseModel


# ==================== 工具函数 ====================

def _score_stars(score: float | None) -> str:
    """评分 → ⭐ 星级字符串。"""
    if score is None:
        return "暂无评分"
    stars = round(score / 2)  # 10 分制 → 5 星
    return "⭐" * max(1, min(5, stars))


def _rank_badge(rank: int | None) -> str:
    """排名 → 徽章。"""
    if rank is None:
        return ""
    if rank <= 3:
        return f"🥇" if rank == 1 else (f"🥈" if rank == 2 else "🥉")
    if rank <= 10:
        return f"🔝#{rank}"
    return f"#{rank}"


def _tags_str(tags: list[str]) -> str:
    """标签列表 → 字符串。"""
    if not tags:
        return ""
    return " · ".join(f"`{t}`" for t in tags[:8])


# ==================== 各领域 Formatter ====================

def format_anime_card_list(model: BaseModel) -> str:
    """动漫推荐卡片列表。

    输出示例::

        ## 🎬 为你推荐

        ### 1. 进击的巨人 The Final Season
        ⭐⭐⭐⭐⭐ 9.1分 | 🔝#2 | `热血` · `战斗` · `剧情`
        > 史诗级收尾，MAPPA制作精良，不可错过的最终章。
    """
    from agent.structured_output.schemas import AnimeRecommendationList

    if not isinstance(model, AnimeRecommendationList):
        return str(model)

    lines = ["## 🎬 动漫推荐"]
    for i, item in enumerate(model.items, 1):
        title = item.chinese_name
        if item.japanese_name:
            title += f"（{item.japanese_name}）"

        lines.append(f"\n### {i}. {title}")

        meta_parts = []
        if item.score is not None:
            meta_parts.append(f"{_score_stars(item.score)} {item.score}分")
        if item.rank is not None:
            meta_parts.append(_rank_badge(item.rank))
        if meta_parts:
            lines.append(" | ".join(meta_parts))

        if item.tags:
            lines.append(_tags_str(item.tags))

        lines.append(f"> {item.reason}")

        if item.url:
            lines.append(f"🔗 [{item.url}]({item.url})")

    return "\n".join(lines)


def format_season_table(model: BaseModel) -> str:
    """季度新番表格。

    输出为 Markdown 表格 + 摘要信息。
    """
    from agent.structured_output.schemas import SeasonOverview

    if not isinstance(model, SeasonOverview):
        return str(model)

    lines = [
        f"## 📺 {model.season_label}",
        f"\n本季度共收录 **{model.total_count}** 部番剧，以下是 Top {len(model.top_items)}：",
        "\n| # | 名称 | 类型 | 评分 | 亮点 |",
        "|---|------|------|------|------|",
    ]

    for i, item in enumerate(model.top_items, 1):
        title = item.chinese_name
        tags = " · ".join(item.tags[:3]) if item.tags else "-"
        score = f"{item.score}" if item.score else "-"
        reason = item.reason[:60] + "…" if len(item.reason) > 60 else item.reason
        lines.append(f"| {i} | {title} | {tags} | {score} | {reason} |")

    return "\n".join(lines)


def format_deep_dive_detail(model: BaseModel) -> str:
    """动漫深度分析详览。"""
    from agent.structured_output.schemas import AnimeDeepDive

    if not isinstance(model, AnimeDeepDive):
        return str(model)

    title = model.chinese_name
    if model.japanese_name:
        title += f"（{model.japanese_name}）"

    lines = [f"## 🔍 深度分析: {title}"]

    if model.score is not None or model.rank is not None:
        parts = []
        if model.score is not None:
            parts.append(f"**评分**: {_score_stars(model.score)} {model.score}/10")
        if model.rank is not None:
            parts.append(f"**排名**: {_rank_badge(model.rank)}")
        lines.append(" | ".join(parts))

    if model.tags:
        lines.append(f"\n**标签**: {_tags_str(model.tags)}")

    if model.synopsis:
        lines.append(f"\n### 📖 剧情简介\n{model.synopsis}")

    if model.cast:
        lines.append("\n### 🎤 配音阵容")
        for c in model.cast:
            char = c.get("character", "?")
            va = c.get("voice_actor", "?")
            lines.append(f"- **{char}**: {va}")

    if model.episode_count:
        lines.append(f"\n📊 共 **{model.episode_count}** 话")

    return "\n".join(lines)


def format_weather_card(model: BaseModel) -> str:
    """天气卡片。"""
    from agent.structured_output.schemas import WeatherReport

    if not isinstance(model, WeatherReport):
        return str(model)

    # 天气 emoji
    cond = model.condition or ""
    emoji = "☀️"
    if any(w in cond for w in ["雨", "rain"]):
        emoji = "🌧️"
    elif any(w in cond for w in ["雪", "snow"]):
        emoji = "❄️"
    elif any(w in cond for w in ["云", "阴", "cloud"]):
        emoji = "☁️"
    elif any(w in cond for w in ["雾", "霾", "haze"]):
        emoji = "🌫️"

    lines = [f"## {emoji} {model.city} 天气"]

    details = []
    if model.temperature is not None:
        details.append(f"🌡️ **温度**: {model.temperature}℃")
    if model.feels_like is not None:
        details.append(f"🤔 **体感**: {model.feels_like}℃")
    if model.humidity is not None:
        details.append(f"💧 **湿度**: {model.humidity}%")
    if model.condition:
        details.append(f"📝 **天气**: {model.condition}")

    if details:
        lines.append(" | ".join(details))

    if model.advice:
        lines.append(f"\n💡 {model.advice}")

    return "\n".join(lines)


def format_file_result(model: BaseModel) -> str:
    """文件操作摘要。"""
    from agent.structured_output.schemas import FileOperationResult

    if not isinstance(model, FileOperationResult):
        return str(model)

    icon = "✅" if model.success else "❌"
    op_map = {"read": "读取", "write": "写入", "list": "列表", "report": "报告"}
    op_text = op_map.get(model.operation, model.operation)

    lines = [f"## {icon} 文件{op_text}"]

    if model.path:
        lines.append(f"\n📁 **路径**: `{model.path}`")
    if model.size_bytes is not None:
        kb = model.size_bytes / 1024
        lines.append(f"📦 **大小**: {kb:.1f} KB")
    if model.summary:
        lines.append(f"\n{model.summary}")

    return "\n".join(lines)


# ==================== Formatter 注册表 ====================

FORMATTER_REGISTRY: dict[str, callable] = {
    "anime_card_list":   format_anime_card_list,
    "season_table":      format_season_table,
    "deep_dive_detail":  format_deep_dive_detail,
    "weather_card":      format_weather_card,
    "file_result":       format_file_result,
}


def format_model(model: BaseModel, formatter_name: str) -> str:
    """使用指定 formatter 格式化模型。

    Args:
        model: 校验通过的 Pydantic 模型。
        formatter_name: FORMATTER_REGISTRY 中的键名。

    Returns:
        格式化的 Markdown 文本。如果 formatter 不存在，返回 str(model)。
    """
    formatter = FORMATTER_REGISTRY.get(formatter_name)
    if formatter:
        return formatter(model)
    return str(model)
