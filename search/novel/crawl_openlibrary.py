"""小说资料采集：Open Library 元数据 + Gutendex 公版书检索。

不下载受版权保护的网络小说正文；仅保存公开书目、作者、摘要和公版书链接。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"
GUTENDEX_URL = "https://gutendex.com/books"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "novel"
HEADERS = {"User-Agent": "MutiRoleAgent/1.0 (public metadata collector)"}


def crawl_novel_metadata(query: str, limit: int = 10) -> Path:
    """抓取公开小说书目和公版书信息，保存为 JSON。"""
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空")

    open_response = requests.get(OPEN_LIBRARY_URL, params={"q": query, "limit": limit}, headers=HEADERS, timeout=20)
    open_response.raise_for_status()
    books = []
    for item in open_response.json().get("docs", []):
        books.append({
            "title": item.get("title", ""),
            "authors": item.get("author_name", []),
            "first_publish_year": item.get("first_publish_year"),
            "subjects": item.get("subject", [])[:20],
            "openlibrary_key": item.get("key", ""),
        })

    guten_response = requests.get(GUTENDEX_URL, params={"search": query}, headers=HEADERS, timeout=20)
    guten_response.raise_for_status()
    public_domain = [
        {
            "title": item.get("title", ""),
            "authors": item.get("authors", []),
            "subjects": item.get("subjects", [])[:20],
            "formats": item.get("formats", {}),
            "copyright": item.get("copyright"),
        }
        for item in guten_response.json().get("results", [])[:limit]
    ]

    data = {
        "schema_version": 1,
        "source": ["Open Library", "Project Gutenberg / Gutendex"],
        "query": query,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "books": books,
        "public_domain_books": public_domain,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", query)[:80] or "novel"
    path = OUTPUT_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(crawl_novel_metadata(input("小说名称：")))
