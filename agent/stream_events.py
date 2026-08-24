"""
流式输出事件类型定义
====================
将 Agent 流式输出拆分为两类事件，供前端按类型分流渲染：

- ``TextChunk``  — 文字片段，前端做逐字打字机效果
- ``ToolEvent``  — 工具调用生命周期，前端做状态指示器/日志

使用方式::

    from agent.stream_events import TextChunk, ToolEvent

    async for event in agent.execute_stream_async(query):
        if isinstance(event, TextChunk):
            ui.write_stream(event.content)    # 打字机
        elif isinstance(event, ToolEvent):
            ui.show_tool_status(event)        # 工具指示器
"""

from dataclasses import dataclass, field

from agent.content import ContentBlock


@dataclass
class TextChunk:
    """文字片段事件。

    每次 Agent 产出一段可见文本时触发（可能是思考过程、
    工具调用前的说明、或最终的完整回答）。
    """
    content: str


@dataclass
class StructuredData:
    """结构化输出事件，在流式输出完成后触发。

    当 LLM 响应中包含符合 Schema 的有效 JSON 数据时，
    此事件携带校验通过的 Pydantic 模型和预格式化的 Markdown。

    - ``schema_type``: Schema 名称（如 "anime_recommendation"）
    - ``model``: 校验通过的 Pydantic 模型实例
    - ``formatted``: 预格式化的 Markdown（供 st.write 直接渲染）
    - ``raw_json``: 原始解析的 JSON dict
    """
    schema_type: str                  # "anime_recommendation"
    model: object                     # Pydantic BaseModel instance
    formatted: str                    # Pre-formatted markdown
    raw_json: dict = field(default_factory=dict)


@dataclass
class ToolEvent:
    """工具调用事件。

    覆盖工具的完整生命周期：

    - ``phase="start"``：模型决定调用工具，携带 tool_name + tool_args
    - ``phase="end"``：工具返回结果，携带 tool_name + result_preview
    """
    phase: str                        # "start" | "end"
    tool_name: str                    # 工具函数名
    tool_args: dict = field(default_factory=dict)   # 调用参数
    result_preview: str = ""          # 返回结果摘要（仅 phase="end"）

    def to_content_block(self) -> ContentBlock:
        """转换为统一内容块，供日志/API 保留工具事件。"""

        return ContentBlock(
            type="json",
            data={
                "phase": self.phase,
                "tool_name": self.tool_name,
                "tool_args": self.tool_args,
                "result_preview": self.result_preview,
            },
            metadata={"kind": "tool_event"},
        )


def event_to_content_block(event: TextChunk | ToolEvent | StructuredData) -> ContentBlock:
    """将现有流事件转换为 P0 内容块。"""

    if isinstance(event, TextChunk):
        return ContentBlock(type="text", data=event.content)
    if isinstance(event, ToolEvent):
        return event.to_content_block()
    return ContentBlock(
        type="json",
        data=event.raw_json,
        metadata={"kind": "structured_data", "schema_type": event.schema_type},
    )


# 工具中文名映射（供前端展示用）
TOOL_DISPLAY_NAMES: dict[str, str] = {
    # 动漫工具
    "search_anime":           "🔍 搜索动漫作品",
    "fetch_anime":     "📋 获取作品详情",
    "get_season_anime":       "📺 季度新番查询",
    # 知识库
    "rag_summarize":          "📚 RAG 知识库检索",
    "download_novel":         "📚 小说下载（RAG）",
    "search_novel":            "🔍 搜索起点小说",
    "fetch_novel":             "📖 获取小说详情",
    "search_game_official":    "🎮 查询游戏官方资讯",
    # 天气工具
    "maps_weather":           "🌤️ 实时天气查询（高德 MCP）",
    "maps_ip_location":       "📍 IP 定位（高德 MCP）",
    "get_public_ip":          "🌐 获取公网 IP",
    # 角色切换
    "switch_persona":         "🎭 切换角色人设",
    "reset_persona":          "🔄 重置角色人设",
    # WebSearch MCP
    "web_search":             "🌐 实时网络搜索",
    "web_search_prime":       "🌐 实时网络搜索（深度）",
}


def get_tool_display_name(tool_name: str) -> str:
    """获取工具的中文展示名，无映射时自动推断。"""
    if not tool_name:
        return "🔧 未知工具"
    if tool_name in TOOL_DISPLAY_NAMES:
        return TOOL_DISPLAY_NAMES[tool_name]
    # web_search 系列自动映射
    if "search" in tool_name.lower():
        return f"🔍 {tool_name}"
    return f"🔧 {tool_name}"
