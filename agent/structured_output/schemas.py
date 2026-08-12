"""
结构化输出 Pydantic 模型定义
============================
定义各领域的输出 Schema 和注册表。

每个 Schema 对应一个 SKILL.md 中声明的 ``output_schema`` 字段。

使用方式::

    from agent.structured_output.schemas import SCHEMA_REGISTRY
    schema_cls = SCHEMA_REGISTRY.get("anime_recommendation")
    model = schema_cls.model_validate(data)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ==================== 动漫领域 ====================

class AnimeItem(BaseModel):
    """单条动漫推荐条目。"""
    chinese_name: str = Field(
        ..., max_length=200,
        description="中文名",
    )
    japanese_name: str = Field(
        default="", max_length=200,
        description="日文名（可选）",
    )
    score: float | None = Field(
        default=None, ge=0, le=10,
        description="Bangumi 评分",
    )
    rank: int | None = Field(
        default=None, ge=1,
        description="全站排名",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="类型标签（最多 10 个）",
    )
    reason: str = Field(
        ..., max_length=500,
        description="推荐理由",
    )
    url: str = Field(
        default="", max_length=500,
        description="作品链接",
    )


class AnimeRecommendationList(BaseModel):
    """动漫推荐列表（对应 recommend-anime Skill）。"""
    type: str = Field(default="anime_recommendation")
    items: list[AnimeItem] = Field(
        ..., min_length=1, max_length=10,
        description="推荐条目列表",
    )


class SeasonOverview(BaseModel):
    """季度新番概览（对应 season-overview Skill）。"""
    type: str = Field(default="season_overview")
    season_label: str = Field(
        ..., max_length=50,
        description="季度标签（如 2026年7月新番）",
    )
    total_count: int = Field(ge=0, description="该季度番剧总数")
    top_items: list[AnimeItem] = Field(
        ..., max_length=10,
        description="Top N 推荐条目",
    )


class AnimeDeepDive(BaseModel):
    """动漫深度分析（对应 anime-deep-dive Skill）。"""
    type: str = Field(default="anime_deep_dive")
    chinese_name: str = Field(..., max_length=200)
    japanese_name: str = Field(default="", max_length=200)
    score: float | None = Field(default=None, ge=0, le=10)
    rank: int | None = Field(default=None, ge=1)
    synopsis: str = Field(default="", max_length=1000, description="剧情简介")
    cast: list[dict] = Field(
        default_factory=list,
        description='配音阵容 [{"character": "..", "voice_actor": ".."}]',
    )
    episode_count: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list)


# ==================== 天气领域 ====================

class WeatherReport(BaseModel):
    """天气报告（对应 weather-lifestyle Skill）。"""
    type: str = Field(default="weather_report")
    city: str = Field(..., max_length=50, description="城市名")
    temperature: float | None = Field(default=None, description="当前温度（℃）")
    humidity: float | None = Field(default=None, description="湿度（%）")
    condition: str = Field(default="", max_length=100, description="天气状况")
    feels_like: float | None = Field(default=None, description="体感温度")
    advice: str = Field(default="", max_length=500, description="生活/看番建议")


# ==================== 文件领域 ====================

class FileOperationResult(BaseModel):
    """文件操作结果（对应 file-processor Skill）。"""
    type: str = Field(default="file_operation")
    operation: str = Field(
        ..., description="操作类型: read | write | list | report",
    )
    path: str = Field(default="", max_length=500, description="文件路径")
    size_bytes: int | None = Field(default=None, description="文件大小")
    success: bool = Field(default=True)
    summary: str = Field(default="", max_length=500, description="操作摘要")


# ==================== 通用 Schema 注册表 ====================

SCHEMA_REGISTRY: dict[str, type[BaseModel]] = {
    "anime_recommendation": AnimeRecommendationList,
    "season_overview":       SeasonOverview,
    "anime_deep_dive":       AnimeDeepDive,
    "weather_report":        WeatherReport,
    "file_operation":        FileOperationResult,
}
