"""为整个工程提供统一的项目根目录与路径解析。"""

from pathlib import Path


def get_project_root() -> Path:
    """返回项目根目录。"""
    return Path(__file__).resolve().parent.parent


def get_project_path(relative_path: str | Path = ".") -> Path:
    """返回位于项目根目录下的 ``Path`` 对象。"""
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return get_project_root() / path


def get_abs_path(relative_path: str | Path) -> str:
    """返回字符串绝对路径，兼容仍需要 ``str`` 的旧调用方。"""
    return str(get_project_path(relative_path))


if __name__ == "__main__":
    print(get_project_path("utils/path_tool.py"))
