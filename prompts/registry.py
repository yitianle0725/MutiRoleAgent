"""本地 Prompt Registry；可选同步到 LangSmith Prompt Hub。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PromptRegistry:
    def __init__(self, base_dir: str | Path = "prompts/versions") -> None:
        self.base_dir = Path(base_dir)

    def get(self, name: str, version: str = "latest") -> str:
        path = self.base_dir / name / f"{version}.txt"
        if not path.exists() and version == "latest":
            path = self.base_dir / name / "v1.txt"
        return path.read_text(encoding="utf-8")

    def metadata(self, name: str, version: str = "latest") -> dict[str, Any]:
        path = self.base_dir / name / f"{version}.json"
        if not path.exists() and version == "latest":
            path = self.base_dir / name / "v1.json"
        if not path.exists():
            return {"name": name, "version": version}
        return json.loads(path.read_text(encoding="utf-8"))

    def list_versions(self, name: str) -> list[str]:
        directory = self.base_dir / name
        return sorted(path.stem for path in directory.glob("*.txt")) if directory.exists() else []


prompt_registry = PromptRegistry()
