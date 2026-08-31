"""Harness 到各交互入口共用的事件协议。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal


HarnessEventType = Literal[
    "run_start",
    "process_text",
    "tool_start",
    "tool_end",
    "structured_data",
    "final_text",
    "run_end",
]


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    """一条可直接通过 SSE 或 WebSocket 发送的公共事件。"""

    type: HarnessEventType
    data: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    sequence: int = 0
    version: int = 1

    def bind(self, *, run_id: str, sequence: int) -> "HarnessEvent":
        """在统一编排边界补齐本轮标识和严格递增序号。"""

        return replace(self, run_id=run_id, sequence=sequence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "type": self.type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "data": dict(self.data),
        }

    @classmethod
    def process_text(cls, text: str, *, delta: bool = False) -> "HarnessEvent":
        return cls(type="process_text", data={"text": text, "delta": delta})

    @classmethod
    def final_text(cls, text: str, *, delta: bool = False) -> "HarnessEvent":
        return cls(type="final_text", data={"text": text, "delta": delta})

    @classmethod
    def tool_start(
        cls,
        *,
        tool_call_id: str,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
    ) -> "HarnessEvent":
        return cls(
            type="tool_start",
            data={
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "tool_args": tool_args or {},
            },
        )

    @classmethod
    def tool_end(
        cls,
        *,
        tool_call_id: str,
        tool_name: str,
        status: Literal["completed", "failed"] = "completed",
        result_preview: str = "",
        duration_ms: float | None = None,
    ) -> "HarnessEvent":
        data: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "status": status,
            "result_preview": result_preview,
        }
        if duration_ms is not None:
            data["duration_ms"] = round(duration_ms, 2)
        return cls(type="tool_end", data=data)

    @classmethod
    def structured_data(
        cls,
        *,
        schema_type: str,
        data: dict[str, Any],
    ) -> "HarnessEvent":
        return cls(
            type="structured_data",
            data={"schema_type": schema_type, "data": data},
        )


# 这些工具只负责 Harness 内部调度，不应出现在用户界面。
INTERNAL_TOOL_NAMES = frozenset({"invoke_skill", "list_skills"})


TOOL_DISPLAY_NAMES: dict[str, str] = {
    "search_anime": "🔎 搜索动漫作品",
    "fetch_anime": "📋 获取作品详情",
    "get_season_anime": "📺 季度新番查询",
    "rag_summarize": "📚 RAG 知识库检索",
    "download_novel": "📚 小说下载（RAG）",
    "search_novel": "🔎 搜索起点小说",
    "fetch_novel": "📙 获取小说详情",
    "search_game_official": "🎮 查询游戏官方资讯",
    "maps_weather": "🌤️ 实时天气查询（高德 MCP）",
    "maps_ip_location": "📍 IP 定位（高德 MCP）",
    "get_public_ip": "🌐 获取公网 IP",
    "web_search": "🌐 实时网络搜索",
    "web_search_prime": "🌐 实时网络搜索（深度）",
}


def get_tool_display_name(tool_name: str) -> str:
    """返回适合界面展示的工具名称。"""

    if not tool_name:
        return "🔧 未知工具"
    if tool_name in TOOL_DISPLAY_NAMES:
        return TOOL_DISPLAY_NAMES[tool_name]
    if "search" in tool_name.lower():
        return f"🔎 {tool_name}"
    return f"🔧 {tool_name}"
