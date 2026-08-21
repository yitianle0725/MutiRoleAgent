"""通过 Jikan v4 API 采集公开动漫资料并保存为 JSON。
api文档：https://docs.api.jikan.moe/
Jikan 是 MyAnimeList 的非官方公开 API。脚本保留 API 原始字段，
不对返回结构做转换，方便后续导入 RAG 或排查数据来源。
"""

from __future__ import annotations

import argparse
import json
import re
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.parse import urlparse

import requests

BASE_URL = "https://api.jikan.moe/v4"
REQUEST_DELAY = 0.6
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "anime" / "jikan" / "jikan_anime_dump.json"
HEADERS = {"User-Agent": "MutiRoleAgent/1.0 (public knowledge collector)"}
SAVE_DIR = Path(r"data/anime/jikan")
SAVE_DIR.mkdir(exist_ok=True, parents=True)
CACHE_DIR = SAVE_DIR / ".cache"
CACHE_DIR.mkdir(exist_ok=True)

# 仅将已验证稳定的接口纳入正式采集任务。
STABLE_ENDPOINTS = {
    "anime_anime_list": "/anime",
    "anime_anime_info": "/anime/{anime_id}",
    "anime_anime_characters": "/anime/{anime_id}/characters",
    "anime_anime_recommendations": "/anime/{anime_id}/recommendations",
    "anime_anime_relations": "/anime/{anime_id}/relations",
    "genres_anime_all": "/genres/anime",
    "genres_anime_genres": "/genres/anime?filter=genres",
    "schedules_main": "/schedules",
    "seasons_now": "/seasons/now",
    "seasons_upcoming": "/seasons/upcoming",
    "top_anime": "/top/anime",
    "top_manga": "/top/manga",
    "top_characters": "/top/characters",
    "watch_recent_episodes": "/watch/episodes",
}

# 静态元数据很少变化；榜单、放送表和近期剧集需要更快更新。
STATIC_TTL_SECONDS = 7 * 24 * 60 * 60
LIVE_TTL_SECONDS = 6 * 60 * 60
LIVE_ENDPOINTS = {
    "anime_anime_list", "schedules_main", "seasons_now", "seasons_upcoming",
    "top_anime", "top_manga", "top_characters", "watch_recent_episodes",
}


def _base_get(url: str, retries: int = 3, timeout: int = 30) -> dict[str, Any]:
    """请求白名单端点；504/429/5xx 使用带抖动的指数退避。"""
    if not _is_stable_url(url):
        raise ValueError("该 Jikan 端点未在稳定白名单中，不参与正式采集")
    for attempt in range(retries):
        sleep_sec = REQUEST_DELAY if attempt == 0 else 2 ** attempt + random.uniform(0, 0.5)
        time.sleep(sleep_sec)
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt + 1 < retries:
                    print(f"[jikan] HTTP {response.status_code}，第 {attempt + 1} 次重试", flush=True)
                    continue
            if response.status_code >= 400:
                raise RuntimeError(f"Jikan HTTP 请求失败 ({response.status_code}): {response.text[:1000]}")
            return response.json()
        except requests.RequestException as exc:
            if attempt + 1 == retries:
                raise RuntimeError(f"无法连接 Jikan API: {exc}") from exc
    raise RuntimeError("Jikan 请求重试次数已用尽")


def _is_stable_url(url: str) -> bool:
    """判断请求是否命中已验证的端点白名单。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "api.jikan.moe":
        return False
    path = parsed.path.removeprefix("/v4")
    if path == "/anime" or path in {"/genres/anime", "/schedules", "/seasons/now", "/seasons/upcoming", "/top/anime", "/top/manga", "/top/characters", "/watch/episodes"}:
        return True
    segments = path.strip("/").split("/")
    return (
        len(segments) == 2 and segments[0] == "anime" and segments[1].isdigit()
        or len(segments) == 3 and segments[0] == "anime" and segments[1].isdigit()
        and segments[2] in {"characters", "recommendations", "relations"}
    )





# ===================== Anime 番剧主接口 =====================
def jikan_anime(mode: str, anime_id:int|None=None, episode:int|None=None) -> dict[str, Any]:
    """
    mode可选值:
    list            /anime                           番剧列表
    info            /anime/{id}                      基础信息
    full            /anime/{id}/full                 完整详情
    characters      /anime/{id}/characters           登场角色
    staff           /anime/{id}/staff                制作人员
    episodes        /anime/{id}/episodes             全部剧集列表
    single_episode  /anime/{id}/episodes/{episode}   指定单集详情
    news            /anime/{id}/news                 相关新闻
    forum           /anime/{id}/forum                论坛话题
    videos          /anime/{id}/videos               相关视频
    video_episodes  /anime/{id}/videos/episodes      剧集视频
    pictures        /anime/{id}/pictures             图片
    statistics      /anime/{id}/statistics           评分统计
    moreinfo        /anime/{id}/moreinfo             更多信息
    recommendations /anime/{id}/recommendations     相似推荐
    userupdates     /anime/{id}/userupdates          用户动态
    reviews         /anime/{id}/reviews              用户评论
    relations       /anime/{id}/relations            关联作品
    themes          /anime/{id}/themes               OP/ED曲目
    external        /anime/{id}/external             外部链接
    streaming       /anime/{id}/streaming            播放平台
    """
    valid_modes = {
        "list","info","full","characters","staff","episodes","single_episode",
        "news","forum","videos","video_episodes","pictures","statistics",
        "moreinfo","recommendations","userupdates","reviews","relations",
        "themes","external","streaming"
    }
    if mode not in valid_modes:
        raise ValueError(f"无效模式，可选列表: {valid_modes}")

    route_map = {
        "list": "",
        "info": "",
        "full": "/full",
        "characters": "/characters",
        "staff": "/staff",
        "episodes": "/episodes",
        "single_episode": "/episodes",
        "news": "/news",
        "forum": "/forum",
        "videos": "/videos",
        "video_episodes": "/videos/episodes",
        "pictures": "/pictures",
        "statistics": "/statistics",
        "moreinfo": "/moreinfo",
        "recommendations": "/recommendations",
        "userupdates": "/userupdates",
        "reviews": "/reviews",
        "relations": "/relations",
        "themes": "/themes",
        "external": "/external",
        "streaming": "/streaming"
    }

    if mode == "list":
        return _base_get(f"{BASE_URL}/anime")
    else:
        if anime_id is None:
            raise ValueError(f"mode={mode} 必须传入 anime_id")
        suffix = route_map[mode]
        if mode == "single_episode":
            if episode is None:
                raise ValueError("single_episode 模式必须传入 episode 集数")
            url = f"{BASE_URL}/anime/{anime_id}{suffix}/{episode}"
        else:
            url = f"{BASE_URL}/anime/{anime_id}{suffix}"
        return _base_get(url)


def jikan_anime_search(
    page: int = 1,
    limit: int = 25,
    q: str = "",
    type_: str = "",
    min_score: float | None = None,
    max_score: float | None = None,
    status: str = "",
    rating: str = "",
    sfw: bool = False,
    genres: str = "",
    genres_exclude: str = "",
    order_by: str = "",
    sort: str = "",
    start_date: str = "",
    end_date: str = "",
    unapproved: bool = False
) -> dict[str, Any]:
    """Jikan 动漫高级搜索接口 GET /anime"""
    params: dict[str, Any] = {"page": page, "limit": limit}
    if q:
        params["q"] = q
    if type_:
        params["type"] = type_
    if min_score is not None:
        params["min_score"] = min_score
    if max_score is not None:
        params["max_score"] = max_score
    if status:
        params["status"] = status
    if rating:
        params["rating"] = rating
    if sfw:
        params["sfw"] = True
    if genres:
        params["genres"] = genres
    if genres_exclude:
        params["genres_exclude"] = genres_exclude
    if order_by:
        params["order_by"] = order_by
    if sort:
        params["sort"] = sort
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if unapproved:
        params["unapproved"] = ""

    query_str = urlencode(params)
    full_url = f"{BASE_URL}/anime?{query_str}"
    return _base_get(full_url)


# 已有调用方的兼容入口；实际请求仍统一走 jikan_anime。
def jikan_anime_by_id(anime_id: int) -> dict[str, Any]:
    return jikan_anime("info", anime_id)


def jikan_anime_characters(anime_id: int) -> dict[str, Any]:
    return jikan_anime("characters", anime_id)


def jikan_anime_episodes(anime_id: int) -> dict[str, Any]:
    return jikan_anime("episodes", anime_id)


def jikan_anime_videos_episodes(anime_id: int) -> dict[str, Any]:
    return jikan_anime("video_episodes", anime_id)


def jikan_anime_recommendations(anime_id: int) -> dict[str, Any]:
    return jikan_anime("recommendations", anime_id)


def jikan_anime_relations(anime_id: int) -> dict[str, Any]:
    return jikan_anime("relations", anime_id)



# ===================== Characters 角色人物接口 =====================
def jikan_characters(mode: str, char_id:int|None=None) -> dict[str, Any]:
    """
    mode可选值:
    list        /characters                 角色列表
    info        /characters/{id}            角色基础信息
    full        /characters/{id}/full       完整详情
    anime       /characters/{id}/anime      登场番剧
    manga       /characters/{id}/manga      登场漫画
    voices      /characters/{id}/voices     声优配音
    pictures    /characters/{id}/pictures   角色图片
    """
    valid_modes = {"list","info","full","anime","manga","voices","pictures"}
    if mode not in valid_modes:
        raise ValueError(f"无效模式，可选列表: {valid_modes}")

    route_map = {
        "list": "",
        "info": "",
        "full": "/full",
        "anime": "/anime",
        "manga": "/manga",
        "voices": "/voices",
        "pictures": "/pictures"
    }

    if mode == "list":
        return _base_get(f"{BASE_URL}/characters")
    else:
        if char_id is None:
            raise ValueError(f"mode={mode} 必须传入 char_id")
        suffix = route_map[mode]
        return _base_get(f"{BASE_URL}/characters/{char_id}{suffix}")


# ===================== Clubs 社团接口 =====================
def jikan_clubs(mode: str, club_id:int|None=None) -> dict[str, Any]:
    """
    mode可选值:
    list        /clubs                社团列表
    info        /clubs/{id}            社团基础信息
    members     /clubs/{id}/members    社团成员列表
    staff       /clubs/{id}/staff      社团管理员
    relations   /clubs/{id}/relations  关联作品
    """
    valid_modes = {"list","info","members","staff","relations"}
    if mode not in valid_modes:
        raise ValueError(f"无效模式，可选列表: {valid_modes}")

    route_map = {
        "list": "",
        "info": "",
        "members": "/members",
        "staff": "/staff",
        "relations": "/relations"
    }

    if mode == "list":
        return _base_get(f"{BASE_URL}/clubs")
    else:
        if club_id is None:
            raise ValueError(f"mode={mode} 必须传入 club_id")
        suffix = route_map[mode]
        return _base_get(f"{BASE_URL}/clubs/{club_id}{suffix}")



# ===================== Genres 题材/标签分类接口 =====================
def jikan_genres(media_type: str, filter_type:str|None=None) -> dict[str, Any]:
    """
    media_type: anime | manga
    filter_type: None / genres / explicit_genres / themes / demographics
    """
    valid_media = {"anime", "manga"}
    valid_filter = {"genres", "explicit_genres", "themes", "demographics", None}

    if media_type not in valid_media:
        raise ValueError(f"media_type可选: {valid_media}")
    if filter_type not in valid_filter:
        raise ValueError(f"filter_type可选: {valid_filter}")

    params = {}
    if filter_type is not None:
        params["filter"] = filter_type

    query_string = urlencode(params)
    url = f"{BASE_URL}/genres/{media_type}"
    if query_string:
        url += "?" + query_string
    return _base_get(url)



# ===================== Magazines 漫画杂志出版社 =====================
def jikan_magazines(page:int|None=None,
                    limit:int|None=None,
                    q:str|None=None,
                    order_by:str|None=None,
                    sort:str|None=None,
                    letter:str|None=None) -> dict[str, Any]:
    """
    获取杂志列表: /magazines
    :param page: 页码
    :param limit: 每页条数
    :param q: 搜索关键词
    :param order_by: 排序字段，可选: mal_id | name | count
    :param sort: 升降序: asc | desc
    :param letter: 返回以此字母开头的条目
    """
    valid_order = {"mal_id", "name", "count", None}
    valid_sort = {"asc", "desc", None}
    if order_by not in valid_order:
        raise ValueError(f"order_by可选值 {valid_order}")
    if sort not in valid_sort:
        raise ValueError(f"sort可选 asc / desc")

    params = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    if q is not None:
        params["q"] = q
    if order_by is not None:
        params["order_by"] = order_by
    if sort is not None:
        params["sort"] = sort
    if letter is not None:
        params["letter"] = letter

    query_string = urlencode(params)
    url = f"{BASE_URL}/magazines"
    if query_string:
        url += "?" + query_string
    return _base_get(url)



# ===================== Manga 漫画接口 =====================
def jikan_manga(mode: str, manga_id:int|None=None) -> dict[str, Any]:
    """
    mode可选值:
    list        /manga                 漫画列表
    info        /manga/{id}            基础信息
    full        /manga/{id}/full       完整详情
    characters  /manga/{id}/characters角色
    news        /manga/{id}/news       新闻
    forum       /manga/{id}/forum      论坛话题
    pictures    /manga/{id}/pictures   图片
    statistics  /manga/{id}/statistics数据统计
    moreinfo    /manga/{id}/moreinfo   更多信息
    recommendations /manga/{id}/recommendations推荐
    userupdates /manga/{id}/userupdates用户更新
    reviews     /manga/{id}/reviews    评论
    relations   /manga/{id}/relations  关联作品
    external    /manga/{id}/external   外部链接
    """
    valid_modes = {
        "list","info","full","characters","news","forum",
        "pictures","statistics","moreinfo","recommendations",
        "userupdates","reviews","relations","external"
    }
    if mode not in valid_modes:
        raise ValueError(f"无效模式，可选列表: {valid_modes}")

    route_map = {
        "list": "",
        "info": "",
        "full": "/full",
        "characters": "/characters",
        "news": "/news",
        "forum": "/forum",
        "pictures": "/pictures",
        "statistics": "/statistics",
        "moreinfo": "/moreinfo",
        "recommendations": "/recommendations",
        "userupdates": "/userupdates",
        "reviews": "/reviews",
        "relations": "/relations",
        "external": "/external"
    }

    if mode == "list":
        return _base_get(f"{BASE_URL}/manga")
    else:
        if manga_id is None:
            raise ValueError(f"mode={mode} 必须传入 manga_id")
        suffix = route_map[mode]
        return _base_get(f"{BASE_URL}/manga/{manga_id}{suffix}")

# ===================== People 声优/工作人员接口 =====================
def jikan_people(mode: str, person_id:int|None=None) -> dict[str, Any]:
    """
    mode可选值:
    list        /people                 人员列表
    info        /people/{id}            人员基础信息
    full        /people/{id}/full       完整详情
    anime       /people/{id}/anime      参与过的番剧作品
    voices      /people/{id}/voices     配音过的角色
    manga       /people/{id}/manga      参与漫画作品
    pictures    /people/{id}/pictures   人物照片
    """
    valid_modes = {"list","info","full","anime","voices","manga","pictures"}
    if mode not in valid_modes:
        raise ValueError(f"无效模式，可选列表: {valid_modes}")

    route_map = {
        "list": "",
        "info": "",
        "full": "/full",
        "anime": "/anime",
        "voices": "/voices",
        "manga": "/manga",
        "pictures": "/pictures"
    }

    if mode == "list":
        return _base_get(f"{BASE_URL}/people")
    else:
        if person_id is None:
            raise ValueError(f"mode={mode} 必须传入 person_id")
        suffix = route_map[mode]
        return _base_get(f"{BASE_URL}/people/{person_id}{suffix}")



# ===================== Producers 制作公司 =====================
def jikan_producers(mode: str, producer_id:int|None=None) -> dict[str, Any]:
    """
    mode: list | info | full | external
    - list: /producers  获取制作商列表
    - info: /producers/{id} 基础信息，必须传入 producer_id
    - full: /producers/{id}/full 完整信息，必须传入 producer_id
    - external: /producers/{id}/external 外部链接，必须传入 producer_id
    """
    valid_modes = {"list", "info", "full", "external"}
    if mode not in valid_modes:
        raise ValueError(f"无效模式，可选值: {valid_modes}")

    if mode == "list":
        return _base_get(f"{BASE_URL}/producers")
    else:
        if producer_id is None:
            raise ValueError(f"mode={mode} 必须传入 producer_id")
        if mode == "info":
            return _base_get(f"{BASE_URL}/producers/{producer_id}")
        elif mode == "full":
            return _base_get(f"{BASE_URL}/producers/{producer_id}/full")
        elif mode == "external":
            return _base_get(f"{BASE_URL}/producers/{producer_id}/external")


# ===================== Random 随机数据 =====================
def jikan_random(resource_type: str) -> dict[str, Any]:
    """
    resource_type: anime | manga | characters | people | users
    """
    valid_types = {"anime", "manga", "characters", "people", "users"}
    if resource_type not in valid_types:
        raise ValueError(f"无效类型，可选值: {valid_types}")
    return _base_get(f"{BASE_URL}/random/{resource_type}")


# ===================== Recommendations 推荐 =====================
def jikan_recommendations(rec_type: str) -> dict[str, Any]:
    """
    rec_type: anime | manga
    """
    valid_types = {"anime", "manga"}
    if rec_type not in valid_types:
        raise ValueError(f"无效类型，可选值: {valid_types}")
    return _base_get(f"{BASE_URL}/recommendations/{rec_type}")


# ===================== Reviews 全网长评 =====================
def jikan_reviews(review_type: str) -> dict[str, Any]:
    """
    review_type: anime | manga
    """
    valid_types = {"anime", "manga"}
    if review_type not in valid_types:
        raise ValueError(f"无效类型，可选值: {valid_types}")
    return _base_get(f"{BASE_URL}/reviews/{review_type}")


# ===================== Schedules 每周播出计划表 =====================
def jikan_schedules() -> dict[str, Any]:
    return _base_get(f"{BASE_URL}/schedules")


# ===================== Seasons 季度番组合集 =====================
def jikan_seasons(season_op: str, year:int|None=None, season:str|None=None) -> dict[str, Any]:
    """
    season_op: now | upcoming | list | year+season
    year+season 需要传入 year, season；
    year: 2020, 2021, 2022, 2023, ...
    season: winter, spring, summer, fall
    """
    valid_ops = {"now", "upcoming", "list", "year+season"}
    if season_op not in valid_ops:
        raise ValueError(f"无效操作，可选值: {valid_ops}")

    if season_op == "now":
        return _base_get(f"{BASE_URL}/seasons/now")
    elif season_op == "upcoming":
        return _base_get(f"{BASE_URL}/seasons/upcoming")
    elif season_op == "list":
        return _base_get(f"{BASE_URL}/seasons")
    elif season_op == "year+season":
        if year is None or season is None:
            raise ValueError("year+season模式必须提供 year 和 season 参数")
        return _base_get(f"{BASE_URL}/seasons/{year}/{season}")


# ===================== Top 排行榜合集 =====================
def jikan_top(top_type: str) -> dict[str, Any]:
    """
    top_type: anime | manga | people | characters | reviews
    """
    valid_types = {"anime", "manga", "people", "characters", "reviews"}
    if top_type not in valid_types:
        raise ValueError(f"无效类型，可选值: {valid_types}")
    return _base_get(f"{BASE_URL}/top/{top_type}")


# ===================== Watch 预告片合集 =====================
def jikan_watch(watch_type: str) -> dict[str, Any]:
    """
    watch_type: recent_episodes | popular_episodes | recent_promos | popular_promos
    """
    route_map = {
        "recent_episodes":    "watch/episodes",
        "popular_episodes":  "watch/episodes/popular",
        "recent_promos":     "watch/promos",
        "popular_promos":    "watch/promos/popular"
    }
    if watch_type not in route_map:
        raise ValueError(f"无效类型，可选: {list(route_map.keys())}")
    return _base_get(f"{BASE_URL}/{route_map[watch_type]}")




def _cache_path(endpoint_name: str, anime_id: int | None = None) -> Path:
    suffix = f"_{anime_id}" if anime_id is not None else ""
    return CACHE_DIR / f"{endpoint_name}{suffix}.json"


def _cache_ttl(endpoint_name: str) -> int:
    return LIVE_TTL_SECONDS if endpoint_name in LIVE_ENDPOINTS else STATIC_TTL_SECONDS


def _load_cached(endpoint_name: str, anime_id: int | None = None) -> dict[str, Any] | None:
    """返回未过期缓存；过期或损坏缓存会在下一步重新采集。"""
    path = _cache_path(endpoint_name, anime_id)
    if not path.exists() or time.time() - path.stat().st_mtime >= _cache_ttl(endpoint_name):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))["data"]
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _save_cached(endpoint_name: str, data: dict[str, Any], anime_id: int | None = None) -> None:
    payload = {
        "endpoint": endpoint_name,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "ttl_seconds": _cache_ttl(endpoint_name),
        "data": data,
    }
    _cache_path(endpoint_name, anime_id).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _get_incremental(endpoint_name: str, request, anime_id: int | None = None) -> tuple[dict[str, Any], bool]:
    """优先使用缓存，只有缓存过期或不存在时才请求网络。"""
    cached = _load_cached(endpoint_name, anime_id)
    if cached is not None:
        return cached, True
    data = request()
    _save_cached(endpoint_name, data, anime_id)
    return data, False


def collect_incremental() -> dict[str, Any]:
    """增量采集稳定端点，单个失败不会中断其余端点。"""
    requests_by_endpoint = {
        "anime_anime_list": lambda: jikan_anime("list"),
        "genres_anime_all": lambda: jikan_genres("anime"),
        "genres_anime_genres": lambda: jikan_genres("anime", "genres"),
        "schedules_main": jikan_schedules,
        "seasons_now": lambda: jikan_seasons("now"),
        "seasons_upcoming": lambda: jikan_seasons("upcoming"),
        "top_anime": lambda: jikan_top("anime"),
        "top_manga": lambda: jikan_top("manga"),
        "top_characters": lambda: jikan_top("characters"),
        "watch_recent_episodes": lambda: jikan_watch("recent_episodes"),
    }
    result: dict[str, Any] = {"results": {}, "cached": [], "updated": [], "failed": {}}
    for name, request in requests_by_endpoint.items():
        try:
            print(f"正在采集 {name}...", flush=True)
            data, from_cache = _get_incremental(name, request)
            result["results"][name] = data
            result["cached" if from_cache else "updated"].append(name)
        except Exception as exc:
            result["failed"][name] = str(exc)
    return result


def collect_anime_incremental(anime_id: int) -> dict[str, Any]:
    """增量采集一个作品的稳定详情、角色、推荐和关系资料。"""
    requests_by_endpoint = {
        "anime_anime_info": lambda: jikan_anime("info", anime_id),
        "anime_anime_characters": lambda: jikan_anime("characters", anime_id),
        "anime_anime_recommendations": lambda: jikan_anime("recommendations", anime_id),
        "anime_anime_relations": lambda: jikan_anime("relations", anime_id),
    }
    result: dict[str, Any] = {"anime_id": anime_id, "results": {}, "cached": [], "updated": [], "failed": {}}
    for name, request in requests_by_endpoint.items():
        try:
            data, from_cache = _get_incremental(name, request, anime_id)
            result["results"][name] = data
            result["cached" if from_cache else "updated"].append(name)
        except Exception as exc:
            result["failed"][name] = str(exc)
    return result


def save_incremental_collection(output: Path = SAVE_DIR / "jikan_incremental_dump.json") -> Path:
    """采集并保存增量结果，记录本轮缓存命中、更新和失败端点。"""
    data = collect_incremental()
    payload = {
        "schema_version": 1,
        "source": "Jikan v4 API",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }
    return save_results(payload, output)


def collect_anime_detail(anime_id: int) -> dict[str, Any]:
    """兼容旧调用方，采集该作品当前白名单允许的详情端点。"""
    return collect_anime_incremental(anime_id)["results"]


def main(anime_id: int, output: Path = DEFAULT_OUTPUT) -> Path:
    """保存一个作品的增量详情采集结果。"""
    payload = {
        "schema_version": 1,
        "source": "Jikan v4 API",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "anime_id": anime_id,
        "results": collect_anime_detail(anime_id),
    }
    return save_results(payload, output)


def save_results(data: dict[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def build_targeted_output(q: str, directory: Path | None = None) -> Path:
    safe_q = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", q).strip("_") or "query"
    return (directory or DEFAULT_OUTPUT.parent) / f"jikan_targeted_q-{safe_q}.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="增量采集 Jikan 稳定动漫端点")
    parser.add_argument("--anime_id", type=int, help="采集指定 MAL anime ID 的详情、角色、推荐和关系")
    parser.add_argument("--output", type=Path, help="覆盖默认输出文件路径")
    args = parser.parse_args()
    if args.anime_id is not None:
        output = args.output or SAVE_DIR / f"jikan_anime_{args.anime_id}.json"
        print(f"已保存: {main(args.anime_id, output)}")
    else:
        output = args.output or SAVE_DIR / "jikan_incremental_dump.json"
        print(f"已保存: {save_incremental_collection(output)}")


if __name__ == "__main__" and False:  # 旧 Watch 接口测试，保留供参考但不作为正式入口。
    out_file = SAVE_DIR / "watch.json"
    results: dict[str, Any] = {}

    watch_task_list = [
        ("recent_episodes", "watch_recent_episodes"),
        ("popular_episodes", "watch_popular_episodes"),
        ("recent_promos", "watch_recent_promos"),
        ("popular_promos", "watch_popular_promos"),
    ]

    for watch_type, key_name in watch_task_list:
        print(f"\n[Watch] run: {watch_type}")
        try:
            res = jikan_watch(watch_type)
            results[key_name] = res
            print(f"✅ {key_name} ok")
        except Exception as e:
            err_msg = str(e)
            print(f"❌ {key_name} fail: {err_msg}")
            results[key_name] = {"error": err_msg}
        time.sleep(2.0)

    save_results(results, out_file)
    print(f"\n🏁 watch全部接口执行完成，输出文件: {out_file.resolve()}")
