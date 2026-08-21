"""公开资料采集器的离线测试，不发起真实网络请求。"""

from pathlib import Path

from search.anime import crawl_public_anime
from search.novel import crawl_openlibrary
from search.game import crawl_hoyolab_wiki


class FakeResponse:
    def __init__(self, payload=None, text: str = ""):
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_anime_public_api_saves_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(crawl_public_anime, "OUTPUT_DIR", tmp_path)
    responses = iter([
        FakeResponse({"data": {"Page": {"media": [{"id": 1, "title": {"romaji": "Test"}}]}}}),
        FakeResponse({"data": [{"mal_id": 2, "title": "Test"}]}),
    ])
    monkeypatch.setattr(crawl_public_anime.requests, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(crawl_public_anime.requests, "get", lambda *args, **kwargs: next(responses))

    path = crawl_public_anime.crawl_anime("Test", limit=1)
    assert path.exists()
    assert '"anilist"' in path.read_text(encoding="utf-8")


def test_anilist_url_extracts_search() -> None:
    url = "https://anilist.co/search/anime?search=Frieren"
    assert crawl_public_anime.extract_anilist_search(url) == "Frieren"


def test_anilist_url_rejects_missing_search() -> None:
    try:
        crawl_public_anime.extract_anilist_search("https://anilist.co/search/anime")
    except ValueError as exc:
        assert "没有关键词" in str(exc)
    else:
        raise AssertionError("缺少搜索词时应抛出 ValueError")


def test_anilist_url_rejects_other_host() -> None:
    try:
        crawl_public_anime.extract_anilist_search("https://example.com/search/anime?search=Test")
    except ValueError as exc:
        assert "AniList 域名" in str(exc)
    else:
        raise AssertionError("非 AniList 域名应被拒绝")


def test_novel_metadata_saves_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(crawl_openlibrary, "OUTPUT_DIR", tmp_path)
    responses = iter([
        FakeResponse({"docs": [{"title": "Test Novel", "author_name": ["Author"]}]}),
        FakeResponse({"results": [{"title": "Public Novel", "authors": []}]}),
    ])
    monkeypatch.setattr(crawl_openlibrary.requests, "get", lambda *args, **kwargs: next(responses))

    path = crawl_openlibrary.crawl_novel_metadata("Test", limit=1)
    assert path.exists()
    assert "Open Library" in path.read_text(encoding="utf-8")


def test_game_wiki_saves_public_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(crawl_hoyolab_wiki, "OUTPUT_DIR", tmp_path)
    html = """<html><head><title>Game Wiki</title><meta property='og:description' content='Info'>
    <script type='application/ld+json'>{"@type":"WebPage"}</script></head>
    <body><a href='/wiki'>Wiki</a></body></html>"""
    monkeypatch.setattr(crawl_hoyolab_wiki.requests, "get", lambda *args, **kwargs: FakeResponse(text=html))

    path = crawl_hoyolab_wiki.crawl_public_wiki("https://example.com/wiki", "Test Game")
    assert path.exists()
    assert "Game Wiki" in path.read_text(encoding="utf-8")
