from search.anime import search_jikan


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {"data": []}
        self.text = "temporary error"

    def json(self):
        return self._payload


def test_base_get_retries_504(monkeypatch):
    responses = iter([FakeResponse(504), FakeResponse(200, {"data": [1]})])
    monkeypatch.setattr(search_jikan.time, "sleep", lambda _: None)
    monkeypatch.setattr(search_jikan.requests, "get", lambda *args, **kwargs: next(responses))
    assert search_jikan._base_get("https://api.jikan.moe/v4/top/anime") == {"data": [1]}


def test_incremental_cache_skips_request(monkeypatch, tmp_path):
    monkeypatch.setattr(search_jikan, "CACHE_DIR", tmp_path)
    search_jikan._save_cached("top_anime", {"data": [1]})
    data, from_cache = search_jikan._get_incremental(
        "top_anime", lambda: (_ for _ in ()).throw(AssertionError("不应请求网络"))
    )
    assert from_cache is True
    assert data == {"data": [1]}


def test_unstable_endpoint_is_rejected():
    assert search_jikan._is_stable_url("https://api.jikan.moe/v4/anime/1/reviews") is False
