"""米游社公开 Wiki 页面资料采集。

只读取无需登录即可访问的页面标题、描述、JSON-LD 和公开链接；不规避反爬、
不调用私有接口，也不采集用户内容。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "game"
HEADERS = {"User-Agent": "MutiRoleAgent/1.0 (public wiki collector)"}


def crawl_public_wiki(url: str, game: str) -> Path:
    """保存公开 Wiki 页的基础资讯，供 RAG 索引而非完整镜像网站。"""
    if not url.startswith("https://"):
        raise ValueError("只允许 HTTPS 公开页面")
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")
    title = _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    description = _meta(soup, "og:description") or _meta(soup, "description")
    json_ld = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            json_ld.append(json.loads(node.get_text()))
        except json.JSONDecodeError:
            continue
    links = sorted({
        requests.compat.urljoin(url, node["href"])
        for node in soup.select("a[href]")
        if node["href"].startswith(("/", "http"))
    })[:200]
    data = {
        "schema_version": 1,
        "source": "HoYoLAB public wiki page",
        "game": game,
        "url": url,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "description": description,
        "json_ld": json_ld,
        "public_links": links,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", game)[:60] or "game"
    path = OUTPUT_DIR / f"{safe_name}_wiki.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _meta(soup: BeautifulSoup, name: str) -> str:
    node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return node.get("content", "").strip() if node else ""


if __name__ == "__main__":
    print(crawl_public_wiki(input("公开 Wiki URL：").strip(), input("游戏名：").strip()))
