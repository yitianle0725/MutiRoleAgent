import json

from search.anime import search_anilist


def test_fetch_anime_list_respects_limit(monkeypatch):
    pages = iter(
        [
            {"media": [{"id": 1}, {"id": 2}], "pageInfo": {"hasNextPage": True}},
            {"media": [{"id": 3}, {"id": 4}], "pageInfo": {"hasNextPage": False}},
        ]
    )
    monkeypatch.setattr(search_anilist, "fetch_anime_page", lambda variables: next(pages))
    items, info = search_anilist.fetch_anime_list({"sort": ["SCORE_DESC"]}, limit=3)
    assert [item["id"] for item in items] == [1, 2, 3]
    assert info["hasNextPage"] is False


def test_main_writes_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(
        search_anilist,
        "collect_categories",
        lambda limit: ({"top_rated": [{"id": 1, "title": {"native": "测试"}}]}, {"season": "SUMMER"}),
    )
    path = search_anilist.main(tmp_path / "dump.json", limit=1)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["categories"]["top_rated"][0]["title"]["native"] == "测试"
