"""Restricted tools for downloading novels into the local novel directory."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from langchain_core.tools import tool

from search.novel import download_novel as novel_client
from utils.path_tool import get_project_path


NOVELS_DIR = get_project_path("search/novel").resolve()
_INVALID_FILE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_filename(name: str) -> str:
    """Return a Windows-safe filename without allowing a caller path."""
    cleaned = _INVALID_FILE_CHARS.sub("_", name).strip(" .")
    return cleaned[:100] or "downloaded_novel"


def _download_first_match(
    novel_name: str,
    output_dir: Path = NOVELS_DIR,
) -> tuple[Path, str, str]:
    """Download the first search result using the existing download client."""
    requested_name = novel_name.strip().casefold()
    for existing_path in output_dir.glob("*.txt"):
        if existing_path.stem.strip().casefold() == requested_name:
            return existing_path.resolve(), existing_path.stem, ""

    try:
        matches = novel_client.get_search(novel_name)
    except SystemExit as error:
        raise RuntimeError("未找到可下载的小说，请提供更准确的书名或作者。") from error

    if not matches:
        raise RuntimeError("未找到可下载的小说，请提供更准确的书名或作者。")

    selected = matches[0]
    book_id = selected.get("book_id", "")
    if not book_id:
        raise RuntimeError("下载源未返回有效书籍标识。")

    title, author = novel_client.get_book_info(book_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / f"{_safe_filename(title)}.txt").resolve()
    if output_path.parent != output_dir.resolve():
        raise RuntimeError("下载文件路径不在允许目录中。")

    try:
        novel_client.download_txt(book_id, str(output_path))
    except SystemExit as error:
        raise RuntimeError("下载源返回失败，请稍后重试。") from error

    if not output_path.is_file():
        raise RuntimeError("下载未生成文件。")
    return output_path, title, author


def _download_novel_sync(novel_name: str) -> str:
    """Run the blocking download operation outside the Agent event loop."""
    name = novel_name.strip()
    if not name:
        return "错误：请提供小说名或作者名。"
    if len(name) > 100 or _INVALID_FILE_CHARS.search(name):
        return "错误：小说名只能包含普通文字，长度不能超过 100 个字符。"

    output_path, title, author = _download_first_match(name)
    size_kb = output_path.stat().st_size / 1024
    return (
        f"下载完成：《{title}》 作者：{author}。"
        f"文件已保存到 search/novel/{output_path.name}，大小 {size_kb:.1f} KB。"
    )


@tool
async def download_novel(novel_name: str) -> str:
    """下载已配置来源中的小说文本，保存到本项目的 search/novel 目录。"""
    return await asyncio.to_thread(_download_novel_sync, novel_name)
