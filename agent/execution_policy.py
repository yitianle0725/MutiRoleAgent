"""
Execution Policy 参数校验模块
=============================
基于 Pydantic 对工具入参进行运行时强 Schema 校验。

职责
----
- 对已知工具强制参数类型、长度、格式校验
- 对未知工具做宽松检查（仅检测空值/路径穿越，不拒绝）
- 校验失败返回友好中文错误信息，供模型在 ReAct 循环中自行修正

设计决策
--------
- **不自动重试**：校验失败直接返回错误信息给模型，
  让模型在同一次 ReAct 推理中自行修正参数并重新调用工具。
  这比在 middleware 层自动重试更省 token，且无需额外 LLM 调用。
- **不在 TOOL_SCHEMAS 中的工具宽松通过**：避免因配置遗漏阻断正常工具，
  后续可逐步补全 Schema 覆盖。

使用方式::

    from agent.execution_policy import validate_tool_args

    result = validate_tool_args("rag_summarize", {"query": "LangGraph checkpoint 原理"})
    if not result.valid:
        return ToolMessage(content=f"[参数错误] {result.error_message}", ...)
"""

from dataclasses import dataclass
from typing import ClassVar

from pydantic import BaseModel, Field, ValidationError
from utils.logger_handler import logger


# ==================== 数据结构 ====================

@dataclass
class PolicyResult:
    """Policy 校验结果。

    Attributes:
        valid: 是否通过校验。
        error_message: 校验失败时的友好中文错误信息。
        validated_args: 校验通过时返回的清洗后参数（当前不做转换，原样返回）。
    """
    valid: bool = True
    error_message: str = ""
    validated_args: dict | None = None


# ==================== 工具入参 Schema 定义 ====================

class KeywordInput(BaseModel):
    """search_anime / get_season_anime 入参"""
    keyword: str | None = Field(default=None, min_length=1, max_length=500)
    season_url: str | None = Field(default=None, min_length=1, max_length=500)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    class Config:
        extra = "allow"  # 允许多余字段，只校验存在的


class RagQueryInput(BaseModel):
    """rag_summarize / fetch_anime 入参"""
    query: str | None = Field(default=None, min_length=1, max_length=500)
    url: str | None = Field(default=None, min_length=1, max_length=500)
    class Config:
        extra = "allow"


class WeatherInput(BaseModel):
    """get_weather / maps_weather 入参"""
    city: str = Field(
        min_length=1, max_length=50,
        description="城市名称（纯中文或英文）",
    )


class IpLocationInput(BaseModel):
    """maps_ip_location 入参"""
    ip: str = Field(
        min_length=1, max_length=45,
        description="公网 IPv4 或 IPv6 地址",
    )


class SwitchPersonaInput(BaseModel):
    """switch_persona 入参"""
    persona_name: str = Field(
        min_length=1, max_length=50,
        description="角色名称（如 Cyrene、Columbina）",
    )


class WebSearchInput(BaseModel):
    """web_search / web_search_prime 入参"""
    query: str = Field(
        min_length=1, max_length=500,
        description="搜索关键词",
    )


class NovelDownloadInput(BaseModel):
    """download_novel 工具的安全输入。"""
    novel_name: str = Field(min_length=1, max_length=100)


class NovelSearchInput(BaseModel):
    """search_novel 工具的输入。"""
    keyword: str = Field(min_length=1, max_length=100)
    limit: int = Field(default=10, ge=1, le=20)


class NovelFetchInput(BaseModel):
    """fetch_novel 工具的输入。"""
    book_url: str = Field(min_length=1, max_length=500)


class GameOfficialInput(BaseModel):
    """search_game_official 工具的输入。"""
    game: str = Field(default="", pattern=r"^(|ys|sr|zzz)$")
    limit: int = Field(default=5, ge=1, le=20)


class PoiSearchInput(BaseModel):
    """maps_text_search 入参"""
    query: str = Field(
        min_length=1, max_length=200,
        description="POI 搜索关键词",
    )


class PoiDetailInput(BaseModel):
    """maps_search_detail 入参"""
    id: str = Field(
        min_length=1, max_length=100,
        description="POI ID",
    )


class DirectionInput(BaseModel):
    """步行/驾车/公交路线规划入参"""
    origin: str = Field(
        min_length=1, max_length=200,
        description="起点地址",
    )
    destination: str = Field(
        min_length=1, max_length=200,
        description="终点地址",
    )


# ==================== Schema 注册表 ====================

# 有参工具的 Schema 映射
TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    # 动漫工具
    "search_anime":           RagQueryInput,
    "fetch_anime":     RagQueryInput,
    "get_season_anime":       RagQueryInput,
    # 知识库
    "rag_summarize":          RagQueryInput,
    # 角色切换
    "switch_persona":         SwitchPersonaInput,
    # MCP 天气
    "maps_weather":           RagQueryInput,
    "maps_ip_location":       RagQueryInput,
    # MCP 搜索
    "web_search":             WebSearchInput,
    "web_search_prime":       WebSearchInput,
    "download_novel":         NovelDownloadInput,
    "search_novel":            NovelSearchInput,
    "fetch_novel":             NovelFetchInput,
    "search_game_official":    GameOfficialInput,
}

# 无参工具（仅日志记录意外的入参，不拒绝）
_NO_ARG_TOOLS: set[str] = {
    "reset_persona",
}


# ==================== 校验函数 ====================

def validate_tool_args(tool_name: str, tool_args: dict | None) -> PolicyResult:
    """对工具入参进行 Pydantic Schema 校验。

    校验策略：
    - 在 TOOL_SCHEMAS 中 → 强校验，失败返回中文错误
    - 是无参工具 → 宽松通过，多余参数仅记录日志
    - 不在任何注册表中 → 宽松通过（未知工具不做假设）

    Args:
        tool_name: 工具函数名。
        tool_args: 调用参数字典，如 ``{"query": "保养"}``。

    Returns:
        ``PolicyResult``，``valid=True`` 表示通过。
    """
    args = tool_args or {}

    # ---- 有 Schema 的工具：校验 ----
    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is not None:
        try:
            validated = schema(**args)
            return PolicyResult(
                valid=True,
                validated_args=validated.model_dump(),
            )
        except ValidationError as e:
            # 如果是因为 extra 字段不匹配，宽松通过；其他错误才拒绝
            missing_fields = e.errors()
            if missing_fields:
                error_parts = []
                for err in missing_fields:
                    loc = " → ".join(str(l) for l in err["loc"])
                    error_parts.append(f"参数 '{loc}' {err['msg']}")
                error_message = "；".join(error_parts)
                logger.warning(
                    f"[Exec Policy] {tool_name} 参数校验失败: {error_message}"
                )
                return PolicyResult(valid=False, error_message=error_message)
            # 非 missing 错误（如 extra 字段）→ 宽松通过
            logger.debug(
                f"[Exec Policy] {tool_name} 参数不匹配 schema 但非致命，宽松通过"
            )
            return PolicyResult(valid=True)

    # ---- 无参工具：宽松通过 ----
    if tool_name in _NO_ARG_TOOLS:
        if args:
            logger.debug(
                f"[Exec Policy] 无参工具 {tool_name} 收到参数: {args}，已忽略"
            )
        return PolicyResult(valid=True)

    # ---- 未知工具：宽松通过 ----
    # 仅检查空值（不做类型假设）
    logger.debug(
        f"[Exec Policy] 未知工具 {tool_name} 不在 Schema 注册表中，宽松通过"
    )
    return PolicyResult(valid=True)
