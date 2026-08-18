"""Tests for the restricted novel download Tool."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.action_gate import action_gate
from agent.execution_policy import validate_tool_args
from tools import novel_tools


def test_download_tool_writes_only_to_given_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        novel_tools.novel_client,
        "get_search",
        lambda name: [{"book_id": "42"}],
    )
    monkeypatch.setattr(
        novel_tools.novel_client,
        "get_book_info",
        lambda book_id: ("A/B", "Author"),
    )
    monkeypatch.setattr(
        novel_tools.novel_client,
        "download_txt",
        lambda book_id, path: Path(path).write_text("content", encoding="utf-8"),
    )

    output_path, title, author = novel_tools._download_first_match("example", tmp_path)
    assert output_path.parent == tmp_path.resolve()
    assert output_path.name == "A_B.txt"
    assert title == "A/B"
    assert author == "Author"


def test_download_tool_reuses_existing_local_novel(tmp_path, monkeypatch) -> None:
    local_file = tmp_path / "斗破苍穹.txt"
    local_file.write_text("existing", encoding="utf-8")
    monkeypatch.setattr(
        novel_tools.novel_client,
        "get_search",
        lambda name: (_ for _ in ()).throw(AssertionError("network lookup should be skipped")),
    )

    output_path, title, author = novel_tools._download_first_match("斗破苍穹", tmp_path)
    assert output_path == local_file.resolve()
    assert title == "斗破苍穹"
    assert author == ""


def test_download_tool_policy_and_gate() -> None:
    assert action_gate.check_tool_call("download_novel", {"novel_name": "example"}).allow
    assert validate_tool_args("download_novel", {"novel_name": ""}).valid is False


def test_download_tool_can_run_asynchronously() -> None:
    result = asyncio.run(novel_tools.download_novel.ainvoke({"novel_name": ""}))
    assert result.startswith("错误：")
