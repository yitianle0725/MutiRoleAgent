"""将四个动漫来源汇总为 Agent 可直接引用的搜索结果。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from search.anime.crawl_bangumi import search_bangumi
from search.anime.search_anilist import search_anime as search_anilist
from search.anime.search_jikan import jikan_anime_search
from utils.path_tool import get_project_path

YUC_DIR = get_project_path("data/anime/yuc")


def search_anime_sources(keyword: str, limit: int = 3) -> dict[str, Any]:
    """依次查询 Bangumi、AniList、Jikan 和已采集的 YUC 季表。"""
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword 不能为空")

    sources: dict[str, Any] = {}
    for name, search in (
        ("bangumi", lambda: _search_bangumi(keyword, limit)),
        ("anilist", lambda: _search_anilist(keyword, limit)),
        ("jikan", lambda: _search_jikan(keyword, limit)),
        ("yuc", lambda: _search_yuc_cache(keyword, limit)),
    ):
        try:
            sources[name] = {"available": True, "results": search()}
        except Exception as exc:
            sources[name] = {"available": False, "results": [], "error": str(exc)}

    has_result = any(source["results"] for source in sources.values())
    return {
        "query": keyword,
        "sources": sources,
        "websearch_fallback_required": not has_result,
        "next_action": "call_web_search" if not has_result else "answer_with_source_citations",
    }


def _search_bangumi(keyword: str, limit: int) -> list[dict[str, Any]]:
    return [
        {
            "title": item.get("title_cn") or item.get("title_jp"),
            "alternate_title": item.get("title_jp"),
            "score": item.get("rating"),
            "url": item.get("url"),
        }
        for item in search_bangumi(keyword, top_n=limit)
    ]


def _search_anilist(keyword: str, limit: int) -> list[dict[str, Any]]:
    items, _ = search_anilist(search=keyword, limit=limit)
    return [
        {
            "id": item.get("id"),
            "title": item.get("title", {}).get("userPreferred"),
            "alternate_title": item.get("title", {}).get("native"),
            "score": item.get("averageScore"),
            "genres": item.get("genres", []),
            "url": item.get("siteUrl"),
        }
        for item in items
    ]


def _search_jikan(keyword: str, limit: int) -> list[dict[str, Any]]:
    items = jikan_anime_search(q=keyword, limit=limit).get("data", [])
    return [
        {
            "id": item.get("mal_id"),
            "title": item.get("title"),
            "alternate_title": item.get("title_japanese"),
            "score": item.get("score"),
            "genres": [genre.get("name") for genre in item.get("genres", [])],
            "url": item.get("url"),
        }
        for item in items
    ]


def _search_yuc_cache(keyword: str, limit: int) -> list[dict[str, Any]]:
    """YUC 无关键词 API，因此查询本地已采集的季度资料。"""
    matches: list[dict[str, Any]] = []
    for path in YUC_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for anime in payload.get("animes", []):
            titles = f"{anime.get('title_cn', '')} {anime.get('title_jp', '')}".lower()
            if keyword.lower() not in titles:
                continue
            matches.append({
                "title": anime.get("title_cn") or anime.get("title_jp"),
                "alternate_title": anime.get("title_jp"),
                "genres": anime.get("tag", ""),
                "season": payload.get("info", {}).get("季度", ""),
                "cache_file": path.name,
            })
            if len(matches) >= limit:
                return matches
    return matches
