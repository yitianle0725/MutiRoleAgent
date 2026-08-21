from search.anime import source_search


def test_all_empty_sources_require_websearch(monkeypatch):
    monkeypatch.setattr(source_search, "_search_bangumi", lambda keyword, limit: [])
    monkeypatch.setattr(source_search, "_search_anilist", lambda keyword, limit: [])
    monkeypatch.setattr(source_search, "_search_jikan", lambda keyword, limit: [])
    monkeypatch.setattr(source_search, "_search_yuc_cache", lambda keyword, limit: [])
    result = source_search.search_anime_sources("不存在的作品")
    assert result["websearch_fallback_required"] is True
    assert result["next_action"] == "call_web_search"


def test_source_results_keep_source_names(monkeypatch):
    monkeypatch.setattr(source_search, "_search_bangumi", lambda keyword, limit: [{"title": "A"}])
    monkeypatch.setattr(source_search, "_search_anilist", lambda keyword, limit: [])
    monkeypatch.setattr(source_search, "_search_jikan", lambda keyword, limit: [])
    monkeypatch.setattr(source_search, "_search_yuc_cache", lambda keyword, limit: [])
    result = source_search.search_anime_sources("A")
    assert result["sources"]["bangumi"]["results"] == [{"title": "A"}]
    assert result["websearch_fallback_required"] is False
