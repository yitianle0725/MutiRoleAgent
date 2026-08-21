import json

from search.anime import search_jikan


def test_collect_anime_detail_combines_verified_endpoints(monkeypatch):
    endpoint_names = ("anime_anime_info", "anime_anime_characters")
    monkeypatch.setattr(
        search_jikan,
        "collect_anime_incremental",
        lambda anime_id: {"results": {name: {"id": anime_id} for name in endpoint_names}},
    )
    results = search_jikan.collect_anime_detail(1)
    assert set(results) == set(endpoint_names)
    assert results["anime_anime_info"]["id"] == 1


def test_main_saves_jikan_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(search_jikan, "collect_anime_detail", lambda anime_id: {"jikan_anime_by_id": {"data": {}}})
    path = search_jikan.main(1, tmp_path / "jikan_anime_dump.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source"] == "Jikan v4 API"
    assert payload["anime_id"] == 1


def test_targeted_output_uses_jikan_q_name(tmp_path):
    path = search_jikan.build_targeted_output("星际牛仔", tmp_path)
    assert path.name == "jikan_targeted_q-星际牛仔.json"
