"""
MCP 客户端管理器：单例模式 + 懒加载 + 工具缓存
全局只创建一次MCP长连接，只拉取一次远端工具，避免重复网络请求。

天气/定位已改用高德 Web API 本地工具（``maps_weather`` / ``maps_ip_location``），
不再走 MCP。当前仅管理 WebSearch MCP 服务，URL 和认证可通过环境变量覆盖：

- ``WEBSEARCH_MCP_URL`` : WebSearch MCP 服务地址（默认 DashScope）
- ``WEBSEARCH_MCP_KEY`` : WebSearch MCP 认证 Key（默认使用 DASHSCOPE_API_KEY）
"""
import os
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool
from utils.logger_handler import logger

load_dotenv()

# API Key（MCP 认证 + 兼容旧变量名）
_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# WebSearch MCP 可配置（默认走 DashScope，可通过环境变量切换到自建服务）
_WEBSEARCH_MCP_URL = os.getenv(
    "WEBSEARCH_MCP_URL",
    "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp",
)
_WEBSEARCH_MCP_KEY = os.getenv("WEBSEARCH_MCP_KEY") or _API_KEY


class McpManager:
    """多 MCP 服务器管理器。

    管理远端 MCP 服务，每个服务独立缓存工具。
    天气/定位已迁移到高德 Web API，本类仅管理 WebSearch MCP。
    """
    _instance: "McpManager | None" = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._client: MultiServerMCPClient | None = None
        # 工具缓存: key=server_name, value=工具列表
        self._server_tools: dict[str, list[BaseTool]] = {}
        self._initialized = True

        # MCP 服务器配置（通过环境变量可切换为自建服务）
        if _WEBSEARCH_MCP_KEY:
            self.mcp_config = {
                "websearch": {
                    "transport": "streamable-http",
                    "url": _WEBSEARCH_MCP_URL,
                    "headers": {"Authorization": f"Bearer {_WEBSEARCH_MCP_KEY}"},
                },
            }
        else:
            self.mcp_config = {}
            logger.warning(
                "[mcp_client] 未配置 DASHSCOPE_API_KEY 或 WEBSEARCH_MCP_KEY，"
                "WebSearch MCP 不可用"
            )

    # ==================== 连接与加载 ====================

    async def _build_client(self) -> MultiServerMCPClient:
        if self._client is None:
            self._client = MultiServerMCPClient(self.mcp_config)
        return self._client

    async def _load_server_tools(self, server_name: str) -> list[BaseTool]:
        """加载单个 MCP 服务器的全部工具（带缓存 + 15s 超时）。

        Args:
            server_name: 服务器名，如 ``"websearch"``。

        Returns:
            该服务器的 BaseTool 列表，失败返回空列表。
        """
        if server_name in self._server_tools:
            return self._server_tools[server_name]

        if server_name not in self.mcp_config:
            logger.warning(f"[mcp_client] 未知服务器: {server_name}")
            self._server_tools[server_name] = []
            return []

        import asyncio
        try:
            client = await self._build_client()
            async with asyncio.timeout(15):
                async with self._client.session(server_name) as session:
                    await session.list_tools()
                    tools = await client.get_tools()
                    # 过滤出来自该服务器的工具
                    server_tools = [
                        t for t in tools
                        if not hasattr(t, 'metadata') or t.metadata is None
                        or t.metadata.get('__mcp_server__') == server_name
                    ]
                    if not server_tools:
                        server_tools = tools  # fallback: metadata 不可靠时全量取
                    self._server_tools[server_name] = server_tools
                    logger.info(f"[mcp_client] {server_name}: {len(server_tools)} 个工具 — "
                                f"{[t.name for t in server_tools]}")
        except asyncio.TimeoutError:
            logger.warning(f"[mcp_client] {server_name} 连接超时（15s）")
            self._server_tools[server_name] = []
        except Exception as e:
            logger.error(f"[mcp_client] {server_name} 连接失败: {e}")
            self._server_tools[server_name] = []

        return self._server_tools[server_name]

    # ==================== 领域查询 ====================

    async def get_domain_tools(self, domain_name: str) -> list[BaseTool]:
        """按领域名获取工具。

        当前支持:
        - ``"websearch"`` → WebSearch MCP 全部工具
        """
        if domain_name in self.mcp_config:
            return await self._load_server_tools(domain_name)

        # 兼容旧的 amap 领域名（天气/定位已改为本地工具，返回空列表）
        if domain_name in ("weather", "location", "poi", "route", "amap"):
            logger.info(
                f"[mcp_client] '{domain_name}' 已迁移到高德 Web API 本地工具，"
                f"跳过 MCP 加载"
            )
            return []

        logger.warning(f"[mcp_client] 未知领域: {domain_name}")
        return []

    # ==================== 管理 ====================

    async def close_connection(self):
        self._client = None
        self._server_tools.clear()

    @classmethod
    def reset_singleton(cls):
        cls._instance = None


# 对外暴露全局唯一管理器实例
mcp_manager = McpManager()
