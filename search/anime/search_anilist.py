"""通过 AniList GraphQL API 批量采集动漫资料。

AniList 搜索页是前端 SPA，网页 HTML 不包含结果；本脚本直接调用公开
GraphQL 接口，并将结构化结果保存为 UTF-8 JSON，方便导入 RAG。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.path_tool import get_project_path

API_ENDPOINT = "https://graphql.anilist.co"
REQUEST_DELAY = 0.8
DEFAULT_OUTPUT = get_project_path("data/anime/anilist/anilist_search_dump.json")
HEADERS = {"User-Agent": "MutiRoleAgent/1.0 (public knowledge collector)"}

GRAPHQL_QUERY = """
query ($search: String, $genre: String, $status: MediaStatus, $format: MediaFormat,
       $averageScore_greater: Int, $sort: [MediaSort], $season: MediaSeason, $seasonYear: Int,
       $page: Int!, $perPage: Int!) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total currentPage lastPage hasNextPage }
    media(type: ANIME, search: $search, genre: $genre, status: $status, format: $format,
          averageScore_greater: $averageScore_greater, sort: $sort, season: $season, seasonYear: $seasonYear) {
      id title { romaji english native userPreferred } synonyms
      description(asHtml: false) format status source countryOfOrigin isAdult
      episodes duration averageScore meanScore popularity favourites
      season seasonYear startDate { year month day } endDate { year month day }
      nextAiringEpisode { airingAt timeUntilAiring episode }
      genres
      tags { name rank isMediaSpoiler }
      coverImage { large medium extraLarge color }
      bannerImage siteUrl
      studios(isMain: true) { nodes { id name siteUrl } }
      relations { edges { relationType node { id title { romaji english native } format status siteUrl } } }
      characters(sort: ROLE, perPage: 20) {
        edges { role node { id name { first middle last full native } image { medium } } }
      }
      staff(sort: RELEVANCE, perPage: 20) {
        edges { role node { id name { first middle last full native } } }
      }
    }
  }
}
"""


def fetch_anime_page(variables: dict[str, Any], retries: int = 3) -> dict[str, Any]:
    """请求一页数据，处理限流、临时服务错误和 GraphQL 错误。"""
    for attempt in range(retries):
        if attempt:
            time.sleep(min(2**attempt, 10))
        else:
            time.sleep(REQUEST_DELAY)
        try:
            response = requests.post(
                API_ENDPOINT,
                json={"query": GRAPHQL_QUERY, "variables": variables},
                headers=HEADERS,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"无法连接 AniList GraphQL API: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            if attempt + 1 < retries:
                continue
        if response.status_code >= 400:
            detail = response.text[:1000].replace("\n", " ")
            raise RuntimeError(f"AniList HTTP 请求失败 ({response.status_code}): {detail}")
        payload = response.json()
        if payload.get("errors"):
            messages = "; ".join(error.get("message", "未知 GraphQL 错误") for error in payload["errors"])
            raise RuntimeError(f"AniList GraphQL 请求失败: {messages}")
        return payload["data"]["Page"]
    raise RuntimeError("AniList 请求重试次数已用尽")


def fetch_anime_list(variables: dict[str, Any], limit: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按分类分页获取动漫，limit 最大为 AniList 单页上限 50。"""
    if limit < 1:
        raise ValueError("limit 必须大于 0")
    items: list[dict[str, Any]] = []
    page = 1
    page_size = min(limit, 50)
    page_info: dict[str, Any] = {}
    while len(items) < limit:
        page_data = fetch_anime_page({**variables, "page": page, "perPage": page_size})
        items.extend(page_data["media"])
        page_info = page_data.get("pageInfo", {})
        if not page_info.get("hasNextPage"):
            break
        page += 1
    return items[:limit], page_info


def search_anime(
    search: str | None = None,
    *,
    genre: str | None = None,
    season: str | None = None,
    seasonYear: int | None = None,
    status: str | None = None,
    format: str | None = None,
    averageScore_greater: int | None = None,
    sort: str = "POPULARITY_DESC",
    limit: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按条件定向搜索动漫，所有条件由 AniList 服务端过滤。"""
    if not any((search, genre, season, seasonYear, status, format, averageScore_greater is not None)):
        raise ValueError("至少提供一个搜索条件")
    if averageScore_greater is not None and not 0 <= averageScore_greater <= 100:
        raise ValueError("averageScore_greater 必须在 0 到 100 之间")
    variables: dict[str, Any] = {"sort": [sort]}
    for name, value in {
        "search": search.strip() if search else None,
        "genre": genre,
        "season": season,
        "seasonYear": seasonYear,
        "status": status,
        "format": format,
        "averageScore_greater": averageScore_greater,
    }.items():
        if value is not None and value != "":
            variables[name] = value
    return fetch_anime_list(variables, limit)


def save_search_results(
    results: list[dict[str, Any]], variables: dict[str, Any], output: Path,
    page_info: dict[str, Any] | None = None,
) -> Path:
    """保存一次定向搜索结果。"""
    payload = {
        "schema_version": 2,
        "source": "AniList GraphQL API",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "query": variables,
        "page_info": page_info or {},
        "results": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def build_targeted_output(filters: dict[str, Any], directory: Path | None = None) -> Path:
    """根据定向条件生成稳定、安全的结果文件名。"""
    output_dir = directory or DEFAULT_OUTPUT.parent
    parts = []
    labels = {
        "search": "search",
        "genre": "genre",
        "season": "season",
        "seasonYear": "seasonYear",
        "status": "status",
        "format": "format",
        "averageScore_greater": "averageScore_greater",
        "sort": "sort",
    }
    for key, label in labels.items():
        value = filters.get(key)
        if value is not None and value != "":
            safe_value = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "_", str(value)).strip("_")
            if safe_value:
                parts.append(f"{label}-{safe_value}")
    filename = "anilist_targeted_" + "_".join(parts) + ".json"
    return output_dir / filename


def _season_after(year: int, season: str) -> tuple[int, str]:
    seasons = ["WINTER", "SPRING", "SUMMER", "FALL"]
    index = seasons.index(season)
    return (year + 1, seasons[0]) if index == 3 else (year, seasons[index + 1])


def collect_categories(limit: int = 10) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """采集趋势、本季、下季、历史热门和高分作品。"""
    now = datetime.now(timezone.utc)
    month = now.month
    season = "WINTER" if month <= 3 else "SPRING" if month <= 6 else "SUMMER" if month <= 9 else "FALL"
    next_year, next_season = _season_after(now.year, season)
    queries = {
        "trending_now": {"sort": ["TRENDING_DESC"]},
        "popular_this_season": {"sort": ["POPULARITY_DESC"], "season": season, "seasonYear": now.year},
        "upcoming_next_season": {"sort": ["POPULARITY_DESC"], "season": next_season, "seasonYear": next_year},
        "all_time_popular": {"sort": ["POPULARITY_DESC"]},
        "top_rated": {"sort": ["SCORE_DESC"]},
    }
    result: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, Any] = {"season": season, "seasonYear": now.year, "nextSeason": next_season, "nextSeasonYear": next_year}
    for name, variables in queries.items():
        print(f"正在采集 {name}...", flush=True)
        result[name], page_info = fetch_anime_list(variables, limit)
        print(f"已完成 {name}: {len(result[name])} 条", flush=True)
        metadata[f"{name}_page_info"] = page_info
    return result, metadata


def main(output: Path = DEFAULT_OUTPUT, limit: int = 10) -> Path:
    categories, metadata = collect_categories(limit)
    payload = {
        "schema_version": 2,
        "source": "AniList GraphQL API",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "query_scope": metadata,
        "categories": categories,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="采集 AniList 动漫分类资料")
    parser.add_argument("--limit", type=int, default=10, help="每个分类最多采集多少条")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON 输出路径")
    parser.add_argument("--search", help="关键词，例如 Attack on Titan")
    parser.add_argument("--genre", help="题材，例如 Action、Romance")
    parser.add_argument("--season", choices=["WINTER", "SPRING", "SUMMER", "FALL"])
    parser.add_argument("--seasonYear", type=int)
    parser.add_argument("--status", help="状态，例如 RELEASING、FINISHED")
    parser.add_argument("--format", help="形式，例如 TV、MOVIE、ONA")
    parser.add_argument("--averageScore_greater", type=int)
    parser.add_argument("--sort", default="POPULARITY_DESC")
    args = parser.parse_args()
    try:
        if any((args.search, args.genre, args.season, args.seasonYear, args.status, args.format, args.averageScore_greater is not None)):
            filters = {
                "search": args.search, "genre": args.genre, "season": args.season,
                "seasonYear": args.seasonYear, "status": args.status,
                "format": args.format, "averageScore_greater": args.averageScore_greater, "sort": args.sort,
            }
            results, page_info = search_anime(
                limit=args.limit,
                **{key: value for key, value in filters.items() if value is not None},
            )
            # 未显式指定输出路径时，按筛选条件命名，保留每次定向搜索结果。
            output = args.output
            if output == DEFAULT_OUTPUT:
                output = build_targeted_output(filters)
            print(f"已保存: {save_search_results(results, filters, output, page_info)}")
        else:
            print("通用采集将请求 5 个分类；可按 Ctrl+C 中止。", flush=True)
            print(f"已保存: {main(args.output, args.limit)}")
    except KeyboardInterrupt:
        print("\n已中止采集，未覆盖正在写入的结果文件。", flush=True)
