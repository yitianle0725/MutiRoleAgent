import json

import pytest

pytest.importorskip("feedparser")

from search.acgn_daily import aggregate


def _empty_config():
    return {
        "rss": [],
        "apis": [],
        "translate": {"enabled": False},
        "site": {"max_items_per_source": 1, "max_total_items": 10, "archive_days": 1, "concurrency": 1},
    }


def test_main_returns_json_serializable_payload_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(aggregate, "CONFIG", _empty_config())
    monkeypatch.setattr(aggregate, "DATA_DIR", tmp_path)
    aggregate.HEALTH.clear()
    payload = aggregate.main(write_files=False)
    assert payload["count"] == 0
    assert json.loads(json.dumps(payload, ensure_ascii=False))["items"] == []
    assert not (tmp_path / "latest.json").exists()


def test_main_writes_json_files_to_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(aggregate, "CONFIG", _empty_config())
    monkeypatch.setattr(aggregate, "DATA_DIR", tmp_path)
    aggregate.HEALTH.clear()
    payload = aggregate.main()
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["count"] == payload["count"]
    assert (tmp_path / "archive" / f"{aggregate.TODAY}.json").exists()
    assert (tmp_path / "feed.xml").exists()
