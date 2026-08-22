"""
Agent 工具集 —— 动漫推荐助手 + 日常陪伴
========================================
动漫搜索（bangumi.lol）、季度新番（yuc.wiki）、天气查询（高德MCP）、
实时搜索（WebSearch MCP）、角色切换。
"""

import sys
import os
import re
import json
import requests
from pathlib import Path

from langchain_core.tools import tool

# 跨目录导入 anime 爬虫模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from search.anime.crawl_bangumi import crawl_subject
from search.anime.crawl_yuc import crawl_season_anime
from search.anime.source_search import search_anime_sources
from rag.rag_service import RagSummarizeService
from utils.logger_handler import logger
from search.novel.crawl_book_info import crawl_search, crawl_book
from search.game.crawl_hoyolab_wiki import crawl_official_bundle

rag = RagSummarizeService()


@tool(description="搜索起点中文网小说，返回前 N 条结果及标题、作者、分类、状态、简介和最新章节。默认返回 10 条，不下载正文。")
async def search_novel(keyword: str, limit: int = 10) -> str:
    if not keyword.strip():
        return "错误：小说搜索关键词不能为空。"
    try:
        result = await crawl_search(keyword, limit=limit, keep_markdown=False)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"[search_novel] 起点搜索失败: {exc}")
        return json.dumps({"query": keyword, "results": [], "websearch_fallback_required": True, "error": str(exc)}, ensure_ascii=False)


@tool(description="获取指定起点小说详情页元数据。入参必须是 qidian.com/book/<id>/ URL；只读取作者、简介、标签、推荐数和章节信息，不下载正文。")
async def fetch_novel(book_url: str) -> str:
    try:
        result = await crawl_book(book_url, keep_markdown=False)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        return json.dumps({"url": book_url, "error": str(exc)}, ensure_ascii=False)


@tool(description="获取米游社三个游戏的官方公告、资讯、活动文章，返回每类前 N 条 title 和 url，以及社区地图。game 可选 ys、sr、zzz；默认抓取全部游戏。")
async def search_game_official(game: str = "", limit: int = 5) -> str:
    try:
        if game and game not in {"ys", "sr", "zzz"}:
            return "错误：game 只能是 ys、sr 或 zzz。"
        paths = await crawl_official_bundle(limit=limit, keep_markdown=False, game_key=game or None)
        payloads = []
        for path in paths:
            try:
                payloads.append(json.loads(Path(path).read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"[search_game_official] 读取结果文件失败: {path}: {exc}")
        return json.dumps(
            {"game": game or "all", "results": payloads, "files": paths},
            ensure_ascii=False,
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"game": game or "all", "articles": [], "websearch_fallback_required": True, "error": str(exc)}, ensure_ascii=False)

# 熔断 fallback 关键词映射
_FALLBACK_KEYWORDS = {
    "search_anime": "search_anime_fallback",
    "get_season_anime": "get_season_anime_fallback",
}


# ==================== 动漫工具 ====================

@tool(description="搜索动漫作品。依次查询 Bangumi、AniList、Jikan 与本地 YUC 季表缓存，并在结果中标记来源。若 websearch_fallback_required 为 true，必须继续调用 web_search。")
def search_anime(keyword: str) -> str:
    try:
        result = search_anime_sources(keyword, limit=3)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(f"[search_anime] 四源聚合失败: {exc}")
        return json.dumps(
            {
                "query": keyword,
                "sources": {},
                "websearch_fallback_required": True,
                "next_action": "call_web_search",
                "error": str(exc),
            },
            ensure_ascii=False,
        )


@tool(description="获取动漫作品详情。入参 url 为作品链接（来自 search_anime 返回的 url 字段），返回完整详情JSON（章节/简介/标签/角色/评分）")
def fetch_anime(url: str) -> str:
    if not url:
        return "错误：请提供有效的作品链接（来自 search_anime 的搜索结果）。"
    detail = crawl_subject(url)
    if not detail:
        return f"获取详情失败，请检查链接是否正确: {url}"
    return json.dumps(detail, ensure_ascii=False, indent=2)


@tool(description="获取指定季度的全部新番列表。入参 season_url 为 yuc.wiki 季度链接（如 https://yuc.wiki/202607/），返回季度概况和所有番剧的标题/类型/标签/制作/放送信息")
def get_season_anime(season_url: str) -> str:
    if not season_url or "yuc.wiki" not in season_url:
        return "错误：请提供有效的 yuc.wiki 季度链接（如 https://yuc.wiki/202607/）。"
    try:
        result = crawl_season_anime(season_url)
        animes = result.get("animes", [])
        if animes:
            brief = []
            for a in animes:
                brief.append({
                    "title_cn": a.get("title_cn", ""),
                    "title_jp": a.get("title_jp", ""),
                    "type": a.get("type", ""),
                    "tag": a.get("tag", ""),
                    "broadcast": a.get("broadcast", ""),
                    "staff": a.get("staff", {}),
                })
            info = result.get("info", {})
            return json.dumps({"info": info, "count": len(brief), "animes": brief[:30]}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[get_season_anime] 爬取失败: {e}，尝试从本地知识库检索")

    # fallback: 从本地知识库搜索
    try:
        import re
        match = re.search(r'/(\d{6})/', season_url)
        season_tag = match.group(1) if match else "202601"
        rag_result = rag.rag_summarize(f"{season_tag} 季度 新番 番剧列表")
        if rag_result and "未在知识库" not in rag_result:
            return f"[本地知识库缓存] {rag_result}"
    except Exception as e:
        logger.warning(f"[get_season_anime] 本地知识库 fallback 也失败: {e}")

    return f"暂时无法获取 {season_url} 的番剧数据（网络不可达且本地无缓存），请稍后重试或尝试其他季度。"


# ==================== 知识库工具（保留） ====================

@tool(description="从动漫知识库中检索相关资料（作品评价、声优介绍、制作公司背景等），返回专业参考内容")
def rag_summarize(query: str) -> str:
    return rag.rag_summarize(query)


# ==================== 角色切换工具（保留） ====================

@tool(description="切换当前对话的角色人设和语气风格。入参 persona_name 为角色名称")
def switch_persona(persona_name: str) -> str:
    """切换角色并生成过渡消息（使用 Persona Engine）。"""
    if persona_name.lower() == "none":
        try:
            from agent.persona.engine import persona_engine
            persona_engine.reset()
        except Exception:
            pass
        return "已切换回默认动漫推荐助手模式"

    # 尝试使用 Persona Engine 生成丰富的过渡消息
    try:
        from agent.persona.engine import persona_engine
        old = persona_engine.get_current_persona()
        msg = persona_engine.switch_character(persona_name, old)
        return msg
    except Exception:
        return f"已切换角色人设为: {persona_name}"


@tool(description="重置角色人设，恢复为默认动漫推荐助手语气")
def reset_persona() -> str:
    """重置角色（使用 Persona Engine）。"""
    try:
        from agent.persona.engine import persona_engine
        persona_engine.reset()
    except Exception:
        pass
    return "已重置为默认动漫推荐助手模式"


# ==================== 网络工具 ====================

@tool(description="实时获取本机公网IP，用于后续定位城市查询天气。内网IP返回空字符串")
def get_public_ip() -> str:
    try:
        res = requests.get("https://ip.3322.net", timeout=5)
        ip = res.text.strip()
        if ip.startswith(("192.168.", "10.", "127.", "172.")):
            logger.info("当前为局域网内网IP，无法进行公网定位")
            return ""
        return ip
    except Exception as e:
        logger.warning(f"获取公网IP失败：{e}")
        return ""


# ==================== 天气工具（Open-Meteo 默认 + 高德可选） ====================
# Open-Meteo: 完全免费，无需 API Key，适合全球天气 → 默认
# 高德天气: 国内数据更精准，需要 AMAP_API_KEY → 配置后自动切换

# WMO 天气代码 → 中文描述
_WMO_WEATHER_MAP: dict[int, str] = {
    0: "晴天", 1: "晴间多云", 2: "多云", 3: "阴天",
    45: "有雾", 48: "雾凇",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "大阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "强雷暴伴大冰雹",
}

# 风向角度 → 中文方位（16 方位）
_WIND_DIRS = ["北", "东北偏北", "东北", "东北偏东", "东", "东南偏东", "东南",
              "东南偏南", "南", "西南偏南", "西南", "西南偏西", "西", "西北偏西",
              "西北", "西北偏北"]


def _om_geocode(city: str) -> dict | None:
    """Open-Meteo Geocoding: 城市名 → {name, lat, lng, country}。"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": 1, "language": "zh", "format": "json"}
    res = requests.get(url, params=params, timeout=5)
    data = res.json()
    results = data.get("results", [])
    if not results:
        return None
    r = results[0]
    return {
        "name": r.get("name", city),
        "country": r.get("country", ""),
        "admin1": r.get("admin1", ""),
        "latitude": r["latitude"],
        "longitude": r["longitude"],
    }


def _om_weather(city: str) -> str:
    """Open-Meteo 天气查询（免费，无需 API Key）。"""
    loc = _om_geocode(city)
    if not loc:
        return f"未找到城市「{city}」的地理坐标，请检查城市名称是否正确。"

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": loc["latitude"],
        "longitude": loc["longitude"],
        "current": (
            "temperature_2m,relative_humidity_2m,apparent_temperature,"
            "weather_code,wind_speed_10m,wind_direction_10m,"
            "precipitation,surface_pressure"
        ),
        "timezone": "auto",
        "forecast_days": 1,
    }
    res = requests.get(url, params=params, timeout=10)
    data = res.json()
    current = data.get("current", {})

    code = current.get("weather_code", 0)
    weather_desc = _WMO_WEATHER_MAP.get(code, f"天气代码{code}")
    wind_deg = current.get("wind_direction_10m", 0)
    wind_dir_index = round(wind_deg / 22.5) % 16
    wind_dir = _WIND_DIRS[wind_dir_index]

    return json.dumps({
        "city": loc["name"],
        "region": f"{loc.get('admin1', '')} {loc.get('country', '')}".strip(),
        "weather": weather_desc,
        "temperature": f"{current.get('temperature_2m', '?')}℃",
        "feels_like": f"{current.get('apparent_temperature', '?')}℃",
        "humidity": f"{current.get('relative_humidity_2m', '?')}%",
        "wind_direction": wind_dir,
        "wind_speed": f"{current.get('wind_speed_10m', '?')} km/h",
        "precipitation": f"{current.get('precipitation', 0)} mm",
        "pressure": f"{current.get('surface_pressure', '?')} hPa",
        "source": "Open-Meteo（免费全球天气）",
        "update_time": current.get("time", ""),
    }, ensure_ascii=False, indent=2)


def _amap_weather(city: str, key: str) -> str:
    """高德天气查询（国内数据更精准，需要 API Key）。"""
    url = "https://restapi.amap.com/v3/weather/weatherInfo"
    params = {"key": key, "city": city, "extensions": "base"}
    res = requests.get(url, params=params, timeout=10)
    data = res.json()

    if data.get("status") != "1":
        return (
            f"高德天气查询失败（城市: {city}），返回: {data.get('info', '未知错误')}。"
            f"请确认城市名称是否正确。"
        )

    lives = data.get("lives", [])
    if not lives:
        return f"未找到城市「{city}」的天气数据，请检查城市名称是否正确。"

    live = lives[0]
    return json.dumps({
        "city": live.get("city", ""),
        "province": live.get("province", ""),
        "weather": live.get("weather", ""),
        "temperature": f"{live.get('temperature', '')}℃",
        "wind_direction": live.get("winddirection", ""),
        "wind_power": live.get("windpower", ""),
        "humidity": f"{live.get('humidity', '')}%",
        "source": "高德天气",
        "update_time": live.get("reporttime", ""),
    }, ensure_ascii=False, indent=2)


@tool(description="根据 IP 地址获取所在城市。入参 ip 为公网 IPv4 地址，返回省份+城市名称。用于天气查询前定位用户所在城市。无需 API Key 也可使用。")
def maps_ip_location(ip: str) -> str:
    """IP → 城市名。优先高德（需 AMAP_API_KEY），fallback 到 ip-api.com（免费）。"""
    if not ip:
        return "错误：请提供有效的公网 IP 地址。"

    # 优先高德（国内 IP 更准）
    amap_key = os.getenv("AMAP_API_KEY")
    if amap_key:
        try:
            url = "https://restapi.amap.com/v3/ip"
            res = requests.get(url, params={"key": amap_key, "ip": ip}, timeout=5)
            data = res.json()
            if data.get("status") == "1":
                province = data.get("province", "")
                city = data.get("city", "")
                if city or province:
                    location = city if city else province
                    return json.dumps({
                        "province": province, "city": city,
                        "adcode": data.get("adcode", ""),
                        "location": location,
                        "source": "高德 IP 定位",
                        "tip": f"用户所在城市: {location}，下一步请调用 maps_weather(city='{location}') 获取天气。",
                    }, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[maps_ip_location] 高德 IP 定位失败，尝试 fallback: {e}")

    # Fallback: 免费 IP 定位（依次尝试，无需 Key）
    for service in [
        {"name": "ipapi.co", "url": f"https://ipapi.co/{ip}/json/", "timeout": 8},
        {"name": "ip-api.com", "url": f"http://ip-api.com/json/{ip}?fields=city,regionName,country&lang=zh-CN", "timeout": 5},
    ]:
        try:
            res = requests.get(service["url"], timeout=service["timeout"])
            data = res.json()
            city = data.get("city", "")
            region = data.get("regionName") or data.get("region", "")
            country = data.get("country_name") or data.get("country", "")
            location = city or region or country
            if location:
                return json.dumps({
                    "city": city,
                    "region": region,
                    "country": country,
                    "location": location,
                    "source": f"{service['name']}（免费）",
                    "tip": f"用户所在城市: {location}，下一步请调用 maps_weather(city='{location}') 获取天气。",
                }, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[maps_ip_location] {service['name']} 失败: {e}")

    return (
        "未能通过 IP 定位到城市（可能为内网环境或海外 IP）。"
        "请直接询问用户所在城市，然后调用 maps_weather(city='城市名') 查询天气。"
    )


@tool(description="根据城市名称获取实时天气。入参 city 为城市中文名（如'北京'、'杭州'），返回天气/温度/湿度/风力等实时数据。无需 API Key 也能使用（免费 Open-Meteo 源）。")
def maps_weather(city: str) -> str:
    """查询天气。有 AMAP_API_KEY 走国内更准的高德，否则走免费 Open-Meteo。"""
    if not city:
        return "错误：请提供有效的城市名称（如'北京'、'杭州'）。"

    # 优先高德（国内数据更精准）
    amap_key = os.getenv("AMAP_API_KEY")
    if amap_key:
        try:
            return _amap_weather(city, amap_key)
        except Exception as e:
            logger.warning(f"[maps_weather] 高德查询失败，尝试 Open-Meteo: {e}")

    # 默认: Open-Meteo（免费，全球覆盖）
    try:
        return _om_weather(city)
    except Exception as e:
        logger.error(f"[maps_weather] Open-Meteo 也失败: {e}")
        return f"天气查询失败（城市: {city}）。请稍后重试或检查城市名称是否正确。错误: {e}"


# ==================== 时间日期工具 ====================

@tool(description="获取当前准确的日期与时间。当用户询问今天日期、几月几号、星期几、现在几点等问题时调用。无需参数。")
def get_current_time() -> str:
    """返回当前年月日、星期、时分秒的格式化字符串。"""
    from datetime import datetime
    now = datetime.now()
    weekday = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    return (
        f"当前日期与时间：\n"
        f"- 日期：{now.strftime('%Y年%m月%d日')}\n"
        f"- 星期：{weekday}\n"
        f"- 时间：{now.strftime('%H:%M:%S')}\n"
        f"- 完整格式：{now.strftime('%Y-%m-%d %H:%M:%S')}（星期{weekday}）"
    )
