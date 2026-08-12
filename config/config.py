MCP_CONFIG = {
    "amap": {
        "url": "https://dashscope.aliyuncs.com/api/v1/mcps/amap-maps/mcp",
        "transport": "streamable-http",
        "headers": {
            "Authorization": f"Bearer {os.getenv('DASHSCOPE_API_KEY')}"
        }
    }
}

TOOL_DOMAINS = {
    "weather": ["maps_weather"],
    "poi": ["maps_around_search", "maps_search_detail", "maps_text_search"],
    # ...
}