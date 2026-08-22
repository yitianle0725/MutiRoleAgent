from pathlib import Path

from search.novel import crawl_book_info


MARKDOWN = """
[人气排序](https://www.qidian.com/all/)

## [夜无疆](https://www.qidian.com/book/1040765595/ "夜无疆最新章节在线阅读")
作者链接 [辰东](https://my.qidian.com/author/1/) | [玄幻](https://www.qidian.com/xuanhuan/) | 连载
这是简介
数字万字 | [第十章](https://www.qidian.com/chapter/1040765595/10/)
## [玄鉴仙族](https://www.qidian.com/book/1035420986/ "玄鉴仙族最新章节在线阅读")
## [普通书](https://www.qidian.com/book/100/ "普通书")
"""


def test_parse_popularity_books():
    books = crawl_book_info.parse_popularity_books(MARKDOWN, limit=2)

    assert books[0] == {
        "title": "夜无疆",
        "url": "https://www.qidian.com/book/1040765595/",
        "author": "辰东",
        "categories": ["玄幻"],
        "status": "连载",
        "description": "这是简介",
        "latest_chapter": {
            "title": "第十章",
            "url": "https://www.qidian.com/chapter/1040765595/10/",
        },
    }
    assert books[1]["title"] == "玄鉴仙族"


def test_build_qidian_url_combines_filters():
    url = crawl_book_info.build_qidian_url("玄幻", "连载", "免费", "30万字以下")

    assert url == "https://www.qidian.com/all/chanId21-action0-vip0-size1/"


def test_parse_rank_books_groups_eight_boards():
    blocks = []
    for board in range(8):
        blocks.append(f"### 榜单{board}[更多](https://www.qidian.com/rank/b{board}/)")
        blocks.append("  * ### NO.1")
        blocks.extend(f"## [小说{board}_{i}](https://www.qidian.com/book/{board * 10 + i}/)" for i in range(10))
    markdown = "\n".join(blocks)

    boards = crawl_book_info.parse_rank_books(markdown)

    assert len(boards) == 8
    assert all(board["count"] == 10 for board in boards)
    assert boards[0]["books"][0]["url"].endswith("/0/")
    assert boards[7]["books"][-1]["url"].endswith("/79/")


def test_validate_book_url():
    assert crawl_book_info._validate_book_url("https://www.qidian.com/book/1035420986/")
    import pytest
    with pytest.raises(ValueError):
        crawl_book_info._validate_book_url("https://www.qidian.com/all/")


def test_parse_book_detail_schema():
    markdown = """# 玄鉴仙族\n作者：季越人 更新时间:2026-08-21 20:42:25\n[最新章节] 第一千五百七十四章 前真 ](https://www.qidian.com/chapter/1/)\n连载 | 签约 | VIP | [仙侠](https://www.qidian.com/xianxia/)\n## 作品简介\n这是简介\n_617.19万_ 字数 _657.51万_ 总推荐 _4.32万_ 周推荐"""
    result = crawl_book_info.parse_book_detail(markdown, "https://www.qidian.com/book/1/")
    assert result["book_title"] == "玄鉴仙族"
    assert result["word_count"] == "617.19万"
    assert result["source"] == "qidian.com"


def test_build_search_url_and_parse_results():
    assert crawl_book_info.build_search_url("斗破苍穹") == "https://www.qidian.com/so/%E6%96%97%E7%A0%B4%E8%8B%8D%E7%A9%B9.html"
    markdown = "\n".join(
        f"## [斗破{i}](https://www.qidian.com/book/{i}/)" for i in range(12)
    )
    books = crawl_book_info.parse_search_books(markdown, 10)
    assert len(books) == 10
    assert books[0]["url"].endswith("/0/")


def test_search_payload_does_not_duplicate_book_urls():
    payload = crawl_book_info.build_search_payload(
        "[人气排序](https://www.qidian.com/all/)\n## [书](https://www.qidian.com/book/1/)",
        "书",
        "https://www.qidian.com/so/%E4%B9%A6.html",
    )
    assert "book_urls" not in payload
    assert payload["books"][0]["url"].endswith("/1/")


def test_parse_requires_popularity_marker():
    assert crawl_book_info.parse_popularity_books("## [普通书](https://www.qidian.com/book/100/)") == []


def test_build_payload_contains_urls():
    payload = crawl_book_info.build_payload(MARKDOWN)

    assert payload["ranking"] == "人气排序"
    assert len(payload["datetime"]) == 19
    assert payload["count"] == 3
    assert payload["books"][0]["url"].endswith("1040765595/")


def test_main_reads_existing_markdown(tmp_path, monkeypatch):
    markdown_path = tmp_path / "result.md"
    markdown_path.write_text(MARKDOWN, encoding="utf-8")
    monkeypatch.setattr(crawl_book_info, "OUTPUT_DIR", Path(tmp_path))
    monkeypatch.setattr(crawl_book_info, "JSON_PATH", tmp_path / "result.json")

    import asyncio

    payload = asyncio.run(crawl_book_info.main(markdown_path=markdown_path, keep_markdown=True))

    assert payload["count"] == 3
    assert (tmp_path / "result.json").exists()
