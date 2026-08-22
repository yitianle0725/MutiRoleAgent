"""使用 Crawl4AI 抓取米游社公开游戏页面。"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.path_tool import get_project_path

OUTPUT_DIR = get_project_path("data/game")
GAMES = {
    "ys": ("原神", "https://www.miyoushe.com/ys/"),
    "sr": ("崩坏星穹铁道", "https://www.miyoushe.com/sr"),
    "zzz": ("绝区零", "https://www.miyoushe.com/zzz"),
}
OFFICIAL_URLS = {
    "ys": "https://www.miyoushe.com/ys/home/28",
    "sr": "https://www.miyoushe.com/sr/home/53",
    "zzz": "https://www.miyoushe.com/zzz/home/58",
}
OFFICIAL_TYPES = {1: "公告", 3: "资讯", 2: "活动"}


def _slug(url: str) -> str:
    return urlparse(url).path.strip("/").split("/")[-1] or "miyoushe"


def _has_real_content(markdown: str) -> bool:
    text = markdown.strip()
    return len(text) > 100 and text not in {"Loading...", "数据加载中"}


async def fetch_by_crawl4ai(url: str) -> str:
    """单次浏览器请求，等待前端渲染后返回 Markdown。"""
    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=True,
        viewport_width=1440,
        viewport_height=900,
    )
    run_config = CrawlerRunConfig(
        page_timeout=60000,
        wait_until="domcontentloaded",
        wait_for_timeout=8000,
        scan_full_page=True,
        scroll_delay=0.3,
        max_scroll_steps=3,
        remove_overlay_elements=True,
    )
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)
    if not result.success:
        raise RuntimeError(result.error_message or "Crawl4AI 抓取失败")
    markdown = (result.markdown or "").strip()
    if not _has_real_content(markdown):
        raise RuntimeError("页面仍是 Loading 空壳，可能需要登录或被站点接口拦截")
    return markdown


def build_payload(game_name: str, url: str, markdown: str) -> dict:
    title = ""
    for line in markdown.splitlines():
        if line.startswith("#"):
            title = re.sub(r"^#+\s*", "", line).strip()
            if title:
                break
    return {
        "schema_version": 1,
        "game": game_name,
        "source": "miyoushe.com",
        "source_url": url,
        "title": title or game_name,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "community_map": parse_community_map(markdown, url),
        "content": markdown,
    }


def parse_community_map(markdown: str, source_url: str) -> list[dict[str, str]]:
    """提取“社区地图”板块中的标题和链接。"""
    marker = re.search(r"^社区地图\s*$", markdown, re.MULTILINE)
    if not marker:
        return []
    end = re.search(r"^了解我们\s*$", markdown[marker.end() :], re.MULTILINE)
    section = markdown[marker.end() : marker.end() + end.start()] if end else markdown[marker.end() :]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for title, href in re.findall(r"\[([^\]]+)\]\(([^)\s]+)", section):
        title = title.strip()
        if not title or href.startswith("javascript:"):
            continue
        url = urljoin(source_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append({"title": title, "url": url})
    return items


def parse_official_articles(markdown: str, source_url: str, category: str, limit: int = 5) -> list[dict[str, str]]:
    """提取官方页面指定分类下的前 limit 篇文章。"""
    if limit < 1:
        raise ValueError("limit 必须大于 0")
    # 页面顶部的三个分类只是筛选导航，文章列表位于三者之后，并不嵌套在某个标题下。
    section = markdown
    articles: list[dict[str, str]] = []
    seen: set[str] = set()
    for title, href in re.findall(r"\[([^\]]+)\]\(([^)\s]+)", section):
        url = urljoin(source_url, href)
        if "/article/" not in url or url in seen:
            continue
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        seen.add(url)
        articles.append({"title": title, "url": url})
        if len(articles) >= limit:
            break
    return articles


async def crawl_game(game_key: str, keep_markdown: bool = False) -> Path:
    if game_key not in GAMES:
        raise ValueError(f"未知游戏: {game_key}，可选: {', '.join(GAMES)}")
    game_name, url = GAMES[game_key]
    markdown = await fetch_by_crawl4ai(url)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"miyoushe_{game_key}.json"
    payload = build_payload(game_name, url, markdown)
    if keep_markdown:
        markdown_path = OUTPUT_DIR / f"miyoushe_{game_key}.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        payload["markdown_path"] = str(markdown_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


async def crawl_official(game_key: str, content_type: int, keep_markdown: bool = False) -> Path:
    """抓取指定游戏米游社“官方”板块。"""
    if game_key not in OFFICIAL_URLS:
        raise ValueError(f"未知游戏: {game_key}")
    if content_type not in OFFICIAL_TYPES:
        raise ValueError("官方板块类型只能是 1（公告）或 3（资讯）")
    game_name = GAMES[game_key][0]
    url = f"{OFFICIAL_URLS[game_key]}?type={content_type}"
    markdown = await fetch_by_crawl4ai(url)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUTPUT_DIR / f"miyoushe_{game_key}_official_type{content_type}.json"
    payload = build_payload(game_name, url, markdown)
    payload["section"] = "官方"
    payload["content_type"] = content_type
    payload["content_type_name"] = OFFICIAL_TYPES[content_type]
    if keep_markdown:
        markdown_path = OUTPUT_DIR / f"miyoushe_{game_key}_official_type{content_type}.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        payload["markdown_path"] = str(markdown_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def crawl_public_wiki(target_url: str, game_name: str) -> Path:
    """兼容旧的同步公开页面元数据接口。"""
    response = requests.get(target_url, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    payload = {
        "game": game_name,
        "url": target_url,
        "title": soup.title.get_text(strip=True) if soup.title else "",
        "description": (soup.select_one('meta[property="og:description"]') or {}).get("content", ""),
        "links": [str(a.get("href")) for a in soup.select("a[href]")],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{_slug(target_url)}_public.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def main(game_key: str | None = None, keep_markdown: bool = False) -> list[str]:
    keys = [game_key] if game_key else list(GAMES)
    results = await asyncio.gather(*(crawl_game(key, keep_markdown) for key in keys))
    return [str(path) for path in results]


async def crawl_all_official(keep_markdown: bool = False) -> list[str]:
    paths = await asyncio.gather(
        *(crawl_official(key, content_type, keep_markdown)
          for key in OFFICIAL_URLS for content_type in OFFICIAL_TYPES)
    )
    return [str(path) for path in paths]


async def crawl_official_bundle(limit: int = 5, keep_markdown: bool = False) -> list[str]:
    """每个游戏抓取公告、资讯、活动并合并到一个 JSON。"""
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    async def one_game(game_key: str) -> str:
        game_name = GAMES[game_key][0]
        base_url = OFFICIAL_URLS[game_key]
        pages: dict[int, str] = {}
        for content_type in (1, 3, 2):
            url = base_url if content_type == 2 else f"{base_url}?type={content_type}"
            pages[content_type] = await fetch_by_crawl4ai(url)
        collected_at = datetime.now(timezone.utc)
        payload = {
            "schema_version": 1,
            "game": game_name,
            "source": "miyoushe.com",
            "source_url": base_url,
            "collected_at": collected_at.isoformat(),
            "datetime": collected_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
            "community_map": parse_community_map(pages[2], base_url),
            "articles": {
                OFFICIAL_TYPES[1]: parse_official_articles(pages[1], f"{base_url}?type=1", OFFICIAL_TYPES[1], limit),
                OFFICIAL_TYPES[3]: parse_official_articles(pages[3], f"{base_url}?type=3", OFFICIAL_TYPES[3], limit),
                OFFICIAL_TYPES[2]: parse_official_articles(pages[2], base_url, OFFICIAL_TYPES[2], limit),
            },
        }
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        json_path = OUTPUT_DIR / f"miyoushe_{game_key}_official.json"
        if keep_markdown:
            for content_type, markdown in pages.items():
                (OUTPUT_DIR / f"miyoushe_{game_key}_official_type{content_type}.md").write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(json_path)

    return list(await asyncio.gather(*(one_game(key) for key in GAMES)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用 Crawl4AI 抓取米游社公开游戏页面")
    parser.add_argument("--game", choices=list(GAMES), help="只抓取指定游戏")
    parser.add_argument("--keep-md", action="store_true", help="同时保存原始 Markdown")
    parser.add_argument("--official", action="store_true", help="抓取三个游戏的公告和资讯板块")
    parser.add_argument("--limit", type=int, default=5, help="每个官方分类提取的 article 数量")
    args = parser.parse_args()
    # 默认执行官方板块采集；指定 --game 时保留主页采集模式。
    if args.official or not args.game:
        print(json.dumps(asyncio.run(crawl_official_bundle(args.limit, args.keep_md)), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(asyncio.run(main(args.game, args.keep_md)), ensure_ascii=False, indent=2))
