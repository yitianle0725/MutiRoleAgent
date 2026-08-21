from search.anime import search_anilist


def test_targeted_search_builds_filters(monkeypatch):
    captured = {}

    def fake_fetch(variables, limit):
        captured.update(variables)
        return [{"id": 1}], {"total": 1}

    monkeypatch.setattr(search_anilist, "fetch_anime_list", fake_fetch)
    results, _ = search_anilist.search_anime(
        search="死神", genre="Action", status="FINISHED", averageScore_greater=70, limit=5
    )
    assert results == [{"id": 1}]
    assert captured["search"] == "死神"
    assert captured["genre"] == "Action"
    assert captured["status"] == "FINISHED"
    assert captured["averageScore_greater"] == 70


def test_targeted_output_name_contains_filters(tmp_path):
    path = search_anilist.build_targeted_output(
        {"search": "死神", "genre": "Action", "status": "FINISHED"}, tmp_path
    )
    assert path.name == "anilist_targeted_search-死神_genre-Action_status-FINISHED.json"
