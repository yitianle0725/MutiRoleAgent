from pathlib import Path

from utils.path_tool import get_abs_path, get_project_path, get_project_root


def test_project_path_uses_pathlib_and_project_root():
    root = get_project_root()
    path = get_project_path("data/anime")
    assert isinstance(root, Path)
    assert isinstance(path, Path)
    assert path == root / "data" / "anime"


def test_abs_path_keeps_string_compatibility():
    assert isinstance(get_abs_path("config/rag.yaml"), str)
