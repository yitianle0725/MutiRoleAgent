"""使用 Crawl4AI 获取起点人气排序书目，并输出结构化 JSON。

本脚本不使用 Jina，也不下载小说正文。Crawl4AI 负责执行浏览器渲染，
Markdown 解析器只提取“人气排序”区域中的作品标题和详情页 URL。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from crawl4ai import AsyncWebCrawler

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utils.path_tool import get_project_path

QIDIAN_URL = "https://www.qidian.com/all/"
QIDIAN_RANK_URL = "https://www.qidian.com/rank/"
OUTPUT_DIR = get_project_path("data/novel")
MARKDOWN_PATH = OUTPUT_DIR / "novel_qidian_crawl4ai_result.md"
JSON_PATH = OUTPUT_DIR / "novel_qidian_popularity_top10.json"
RANK_JSON_PATH = OUTPUT_DIR / "novel_qidian_rank.json"
RANK_MARKDOWN_PATH = OUTPUT_DIR / "novel_qidian_rank.md"
MAX_CONTENT_LENGTH = 32 * 1024

CATEGORY_CODES = {
    "玄幻": "chanId21", "奇幻": "chanId22", "武侠": "chanId23",
    "仙侠": "chanId24", "都市": "chanId4", "现实": "chanId15",
    "军事": "chanId6", "历史": "chanId5", "游戏": "chanId8",
    "体育": "chanId7", "科幻": "chanId9", "诸天无限": "chanId42",
    "悬疑灵异": "chanId10", "轻小说": "chanId80", "短篇": "chanId30083",
}
STATUS_CODES = {"连载": "action0", "完本": "action1"}
VIP_CODES = {"免费": "vip0", "VIP": "vip1"}
SIZE_CODES = {
    "30万字以下": "size1", "30-50万字": "size2", "50-100万字": "size3",
    "100-200万字": "size4", "200万字以上": "size5",
}
QUALITY_CODES = {"签约作品": "sign1", "精品小说": "sign2"}
UPDATE_CODES = {"三日内": "update1", "七日内": "update2", "半月内": "update3", "一月内": "update4"}


def build_qidian_url(
    category: str | None = None,
    status: str | None = None,
    vip: str | None = None,
    size: str | None = None,
    quality: str | None = None,
    update: str | None = None,
    tag: str | None = None,
) -> str:
    """按起点筛选规则拼接 URL；所有参数可组合。"""
    codes: list[str] = []
    mappings = (
        (category, CATEGORY_CODES, "分类"), (status, STATUS_CODES, "状态"),
        (vip, VIP_CODES, "属性"), (size, SIZE_CODES, "字数"),
        (quality, QUALITY_CODES, "品质"), (update, UPDATE_CODES, "更新时间"),
    )
    for value, mapping, label in mappings:
        if value in (None, "", "全部"):
            continue
        if value not in mapping:
            raise ValueError(f"{label}筛选值无效: {value}，可选: {', '.join(mapping)}")
        codes.append(mapping[value])
    if tag and tag != "全部":
        codes.append(f"tag{quote(tag, safe='')}")
    suffix = "-".join(codes)
    return f"{QIDIAN_URL}{suffix + '/' if suffix else ''}"


def build_search_url(keyword: str, encoded: bool = True) -> str:
    """构造起点小说搜索 URL。"""
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("搜索关键词不能为空")
    value = quote(keyword, safe="") if encoded else keyword
    return f"https://www.qidian.com/so/{value}.html"


def parse_search_books(markdown: str, limit: int = 10) -> list[dict[str, str]]:
    """从搜索结果 Markdown 中提取前 limit 本小说。"""
    if limit < 1:
        raise ValueError("limit 必须大于 0")
    result_start = re.search(r"^#\s+[^\n]+\n[^\n]*相关作品", markdown, re.MULTILINE)
    if result_start:
        markdown = markdown[result_start.end():]
    pagination = re.search(r"^\s*\*\s+\[<\]\(javascript:;\)", markdown, re.MULTILINE)
    if pagination:
        markdown = markdown[:pagination.start()]
    pattern = re.compile(
        r"^###+\s+\[\s*([^\]]+?)\s*\]\((https?://(?:www\.)?qidian\.com/book/[^)\s]+)[^\n]*\)",
        re.MULTILINE,
    )
    books: list[dict[str, str]] = []
    seen: set[str] = set()
    matches = list(pattern.finditer(markdown))
    if not matches:
        fallback = re.compile(r"\[([^\]]+)\]\((https?://(?:www\.)?qidian\.com/book/[^)\s]+)")
        return [{"title": m.group(1).strip(), "url": m.group(2)} for m in list(fallback.finditer(markdown))[:limit]]
    for index, match in enumerate(matches):
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        url = urljoin(QIDIAN_URL, match.group(2))
        if not title or title.startswith("!") or url in seen:
            continue
        seen.add(url)
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        books.append(_parse_book_block(title, url, markdown[match.end():block_end]))
        if len(books) >= limit:
            break
    return books


def build_search_payload(markdown: str, keyword: str, search_url: str, limit: int = 10) -> dict:
    collected_at = datetime.now(timezone.utc)
    books = parse_search_books(markdown, limit)
    return {
        "schema_version": 1,
        "source": "qidian.com",
        "search_keyword": keyword,
        "search_url": search_url,
        "datetime": collected_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "collected_at": collected_at.isoformat(),
        "count": len(books),
        "books": books,
    }


def parse_popularity_books(markdown: str, limit: int = 10) -> list[dict[str, str]]:
    """解析 Markdown 中“人气排序”下的作品链接。"""
    if limit < 1:
        raise ValueError("limit 必须大于 0")

    marker = re.search(r"\[[^\]]*人气排序[^\]]*\]\([^)]*all/[^)]*\)", markdown)
    if not marker:
        return []

    section = markdown[marker.end():]
    # Crawl4AI 会把书名渲染成二级标题：## [夜无疆](https://www.qidian.com/book/...)
    pattern = re.compile(
        r"^##\s+\[([^\]]+)\]\((https?://(?:www\.)?qidian\.com/book/[^)\s]+)[^\n]*\)\s*$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(section))
    books: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        title = re.sub(r"\s+", " ", match.group(1)).strip()
        url = urljoin(QIDIAN_URL, match.group(2))
        if not title or url in seen:
            continue
        seen.add(url)
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        block = section[match.end():block_end]
        books.append(_parse_book_block(title, url, block))
        if len(books) >= limit:
            break
    return books


def _parse_book_block(title: str, url: str, block: str) -> dict[str, str | dict | list]:
    """解析一本书标题下面的作者、分类、简介和最新章节信息。"""
    links = re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)", block)
    author = ""
    categories: list[str] = []
    for text, link in links:
        text = re.sub(r"\s+", " ", text).strip()
        if "/author/" in link:
            author = text
        elif (
            "/chapter/" not in link
            and "/book/" not in link
            and text
            and not text.startswith("!")
        ):
            categories.append(text)

    chapter = next(
        ({"title": text.strip(), "url": link} for text, link in links if "/chapter/" in link),
        None,
    )
    if chapter:
        chapter["title"] = re.sub(r"^最新更新\s*", "", chapter["title"])
    lines = [re.sub(r"\s+", " ", line).strip() for line in block.splitlines()]
    lines = [line for line in lines if line and not line.startswith("!")]
    description = ""
    for line in lines:
        if "[" not in line and "万字" not in line and not line.startswith("_"):
            description = line
            break

    status = ""
    for candidate in ("连载", "完本", "完结"):
        if candidate in block:
            status = candidate
            break

    result: dict[str, str | dict | list] = {
        "title": title,
        "url": url,
        "author": author,
        "categories": list(dict.fromkeys(categories)),
        "status": status,
        "description": description,
    }
    if chapter:
        result["latest_chapter"] = chapter
    # 字数由起点反爬字体映射生成，如“𘢱𘢯...万字”，无法可靠还原，故不输出。
    return result


async def fetch_by_crawl4ai(url: str) -> str:
    """通过本地浏览器抓取起点页面 Markdown。"""
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, timeout=45, wait_for=8000)
        if not result.success:
            raise RuntimeError(result.error_message or "Crawl4AI 抓取失败")
        return result.markdown.strip()[:MAX_CONTENT_LENGTH]


def build_payload(markdown: str, limit: int = 10, source_url: str = QIDIAN_URL) -> dict:
    books = parse_popularity_books(markdown, limit)
    collected_at = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "source": "起点中文网",
        "source_url": source_url,
        "ranking": "人气排序",
        "collected_at": collected_at.isoformat(),
        "datetime": collected_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(books),
        "books": books,
    }


def parse_rank_books(markdown: str, board_count: int = 8, per_board: int = 10) -> list[dict]:
    """按 Markdown 中的 ``NO.1`` 区块和榜单链接提取真实榜单。"""
    if board_count < 1 or per_board < 1:
        raise ValueError("board_count 和 per_board 必须大于 0")
    pattern = re.compile(
        r"\[([^\]]+)\]\((https?://(?:www\.)?qidian\.com/book/[^)\s]+)",
    )
    board_heading = re.compile(
        r"^###\s+(.+?)\[.*?更多.*?\]\((https://www\.qidian\.com/rank/[^)]+)\)", re.MULTILINE
    )
    headings = list(board_heading.finditer(markdown))
    markers = list(re.finditer(r"^\s*\* ### NO\.1\s*$", markdown, re.MULTILINE))
    boards: list[dict] = []
    used_board_urls: set[str] = set()
    for index, marker in enumerate(markers):
        heading = next((item for item in reversed(headings) if item.start() < marker.start()), None)
        if not heading or heading.group(2) in used_board_urls:
            continue
        end = markers[index + 1].start() if index + 1 < len(markers) else len(markdown)
        block = markdown[marker.end() : end]
        books: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in pattern.finditer(block):
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            url = urljoin(QIDIAN_RANK_URL, match.group(2))
            if not title or title.startswith("!") or url in seen:
                continue
            seen.add(url)
            books.append({"title": title, "url": url})
            if len(books) >= per_board:
                break
        if len(books) != per_board:
            continue
        used_board_urls.add(heading.group(2))
        name = re.sub(r"\s+", " ", heading.group(1)).strip(" _")
        boards.append({"name": name, "url": heading.group(2), "count": len(books), "books": books})
        if len(boards) >= board_count:
            break
    return boards


def build_rank_payload(markdown: str) -> dict:
    boards = parse_rank_books(markdown)
    collected_at = datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "source": "起点中文网",
        "source_url": QIDIAN_RANK_URL,
        "datetime": collected_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "collected_at": collected_at.isoformat(),
        "board_count": len(boards),
        "book_count": sum(board["count"] for board in boards),
        "boards": boards,
    }


def _validate_book_url(book_url: str) -> str:
    parsed = urlparse(book_url)
    host = (parsed.hostname or "").lower()
    if host not in {"qidian.com", "www.qidian.com"} or not re.fullmatch(r"/book/\d+/?", parsed.path):
        raise ValueError("book_url 必须是 https://www.qidian.com/book/<数字>/ 格式")
    return book_url


def _book_file_stem(book_url: str) -> str:
    book_id = re.search(r"/book/(\d+)", book_url).group(1)
    return f"novel_qidian_book_{book_id}"


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def parse_book_detail(markdown: str, book_url: str) -> dict:
    """按单本小说 JSON schema 解析起点详情页 Markdown。"""
    title = _first_match(r"^#\s+(.+?)\s*$", markdown)
    author_name = _first_match(r"作者[：:]?\s*([^\n]+?)\s*(?:更新时间|$)", markdown)
    update_time = _first_match(r"更新时间[：:]?\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", markdown)
    latest_chapter = _first_match(r"最新章节[^\n]*?\s+([^\]\n]+?)\s*\]", markdown)
    tags_line = _first_match(r"^((?:连载|完本).+?)\s*$", markdown)
    tags = re.findall(r"(?<![\w])(?:连载|完本|签约|VIP)(?![\w])", tags_line)
    tags.extend(re.findall(r"\[([^\]]+)\]\(https?://www\.qidian\.com/(?:xuanhuan|qihuan|wuxia|xianxia|dushi|xianshi|junshi|lishi|youxi|tiyu|kehuan|2cy|all/chanId)[^)]*\)", tags_line))
    description = _first_match(r"^##\s+作品简介\s*$\s*([\s\S]*?)(?=^\s*\[|^###|\Z)", markdown)
    description = re.sub(r"\s+", "", description)
    cover_url = _first_match(r"!\[[^\]]*\]\((https?://bookcover\.yuewen\.com/[^)]+)\)", markdown)
    word_count = _first_match(r"_([\d.]+万)_?\s*字(?:数)?", markdown)
    total_recommend = _first_match(r"_([\d.]+万)_\s*总推荐", markdown)
    weekly_recommend = _first_match(r"_([\d.]+万)_\s*周推荐", markdown)
    badge = _first_match(r"\]\([^)]*/author/[^)]*\)\s*\n*##?\s*\[[^\]]+\]", "")
    badge = _first_match(r"\[!\[[^\]]*\]\([^)]*\)\s*([^\]]+?)\s*\]", markdown)
    author_intro = _first_match(r"^##\s+\[[^\]]+\]\(https?://my\.qidian\.com/author/[^)]*\)[\s\S]*?\n([^\n]+)\n作品总数", markdown)
    work_num = _first_match(r"作品总数\s*\n_?(\d+)_?", markdown)
    accumulated_words = _first_match(r"累计字数\s*\n_?([\d.]+万)_?", markdown)
    creation_days = _first_match(r"创作天数\s*\n_?(\d+)_?", markdown)
    collected_at = datetime.now(timezone.utc)
    return {
        "book_title": title,
        "author_name": author_name,
        "update_time": update_time,
        "latest_chapter": latest_chapter,
        "tags": list(dict.fromkeys(tags)),
        "description": description,
        "word_count": word_count,
        "total_recommend": total_recommend,
        "weekly_recommend": weekly_recommend,
        "author_info": {
            "badge": badge,
            "intro": author_intro,
            "work_num": int(work_num) if work_num else None,
            "accumulated_words": accumulated_words,
            "creation_days": int(creation_days) if creation_days else None,
        },
        "book_url": book_url,
        "cover_url": cover_url,
        "collected_at": collected_at.isoformat(),
        "source": "qidian.com",
    }


async def crawl_book(book_url: str, refresh: bool = False, keep_markdown: bool = False) -> dict:
    """抓取指定起点小说详情页，保存原始 Markdown 和页面摘要 JSON。"""
    book_url = _validate_book_url(book_url)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = _book_file_stem(book_url)
    markdown_path = OUTPUT_DIR / f"{stem}.md"
    json_path = OUTPUT_DIR / f"{stem}.json"
    if refresh or not markdown_path.exists() or not keep_markdown:
        markdown = await fetch_by_crawl4ai(book_url)
        if keep_markdown:
            markdown_path.write_text(markdown, encoding="utf-8")
        else:
            markdown_path.unlink(missing_ok=True)
    else:
        markdown = markdown_path.read_text(encoding="utf-8")

    payload = parse_book_detail(markdown, book_url)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


async def crawl_search(
    keyword: str,
    limit: int = 10,
    refresh: bool = False,
    keep_markdown: bool = False,
) -> dict:
    """抓取起点搜索结果，优先使用 UTF-8 百分号编码 URL。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    encoded_url = build_search_url(keyword, encoded=True)
    raw_url = build_search_url(keyword, encoded=False)
    safe_keyword = re.sub(r"[^\w.-]+", "_", keyword.strip())
    markdown_path = OUTPUT_DIR / f"novel_qidian_search_{safe_keyword}.md"
    json_path = OUTPUT_DIR / f"novel_qidian_search_{safe_keyword}_top{limit}.json"

    if refresh or not markdown_path.exists() or not keep_markdown:
        try:
            markdown = await fetch_by_crawl4ai(encoded_url)
            books = parse_search_books(markdown, limit)
            search_url = encoded_url
            if not books:
                markdown = await fetch_by_crawl4ai(raw_url)
                search_url = raw_url
        except Exception:
            markdown = await fetch_by_crawl4ai(raw_url)
            search_url = raw_url
        if keep_markdown:
            markdown_path.write_text(markdown, encoding="utf-8")
    else:
        markdown = markdown_path.read_text(encoding="utf-8")
        search_url = encoded_url

    payload = build_search_payload(markdown, keyword, search_url, limit)
    if keep_markdown:
        payload["markdown_path"] = str(markdown_path)
    else:
        markdown_path.unlink(missing_ok=True)
    payload["saved_path"] = str(json_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


async def main(
    limit: int = 10,
    markdown_path: Path | None = None,
    source_url: str = QIDIAN_URL,
    json_path: Path | None = None,
    keep_markdown: bool = False,
) -> dict:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    markdown_path = markdown_path or MARKDOWN_PATH
    json_path = json_path or JSON_PATH
    # 已有 Markdown 时直接解析，避免重复请求；传入 --refresh 才重新抓取。
    if markdown_path.exists() and keep_markdown:
        markdown = markdown_path.read_text(encoding="utf-8")
    else:
        markdown = await fetch_by_crawl4ai(source_url)
        if keep_markdown:
            markdown_path.write_text(markdown, encoding="utf-8")
        else:
            markdown_path.unlink(missing_ok=True)

    payload = build_payload(markdown, limit, source_url)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["saved_path"] = str(json_path)
    return payload


async def crawl_rank(keep_markdown: bool = False, refresh: bool = False) -> dict:
    """抓取 8 个榜单并保存 80 本书的 URL。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if RANK_MARKDOWN_PATH.exists() and keep_markdown and not refresh:
        markdown = RANK_MARKDOWN_PATH.read_text(encoding="utf-8")
    else:
        markdown = await fetch_by_crawl4ai(QIDIAN_RANK_URL)
        if keep_markdown:
            RANK_MARKDOWN_PATH.write_text(markdown, encoding="utf-8")
        else:
            RANK_MARKDOWN_PATH.unlink(missing_ok=True)
    payload = build_rank_payload(markdown)
    RANK_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["saved_path"] = str(RANK_JSON_PATH)
    if keep_markdown:
        payload["markdown_path"] = str(RANK_MARKDOWN_PATH)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="提取起点人气排序小说 URL")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--refresh", action="store_true", help="重新使用 Crawl4AI 抓取页面")
    parser.add_argument("--rank", action="store_true", help="抓取起点 8 个榜单，每榜 10 本")
    parser.add_argument("--book-url", help="抓取指定起点小说详情页，例如 https://www.qidian.com/book/1035420986/")
    parser.add_argument("--search", help="搜索小说名称，例如 斗破苍穹")
    parser.add_argument("--keep-md", action="store_true", help="保留搜索结果 Markdown，默认不保留")
    parser.add_argument("--category", choices=[*CATEGORY_CODES, "全部"], help="分类")
    parser.add_argument("--status", choices=[*STATUS_CODES, "全部"], help="状态")
    parser.add_argument("--vip", choices=[*VIP_CODES, "全部"], help="属性")
    parser.add_argument("--size", choices=[*SIZE_CODES, "全部"], help="字数范围")
    parser.add_argument("--quality", choices=[*QUALITY_CODES, "全部"], help="品质")
    parser.add_argument("--update", choices=[*UPDATE_CODES, "全部"], help="更新时间")
    parser.add_argument("--tag", help="标签，例如 热血、系统流")
    args = parser.parse_args()
    if args.search:
        print(json.dumps(asyncio.run(crawl_search(args.search, args.limit, args.refresh, args.keep_md)), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if args.book_url:
        print(json.dumps(asyncio.run(crawl_book(args.book_url, args.refresh, args.keep_md)), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if args.rank:
        print(json.dumps(asyncio.run(crawl_rank(args.keep_md, args.refresh)), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    source_url = build_qidian_url(args.category, args.status, args.vip, args.size, args.quality, args.update, args.tag)
    suffix = re.sub(r"[^a-zA-Z0-9_-]+", "_", source_url.removeprefix(QIDIAN_URL).strip("/") or "all")
    markdown_path = OUTPUT_DIR / f"novel_qidian_{suffix}.md"
    json_path = OUTPUT_DIR / f"novel_qidian_{suffix}_top{args.limit}.json"
    if args.refresh:
        markdown_path.unlink(missing_ok=True)
    print(json.dumps(asyncio.run(main(args.limit, markdown_path, source_url, json_path, args.keep_md)), ensure_ascii=False, indent=2))
