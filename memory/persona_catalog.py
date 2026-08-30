"""从配置生成稳定的 Persona 标识和展示信息。"""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from utils.path_tool import get_abs_path


@dataclass(frozen=True, slots=True)
class PersonaInfo:
    persona_id: str
    name: str
    display_name: str


class PersonaCatalog:
    def list(self) -> list[PersonaInfo]:
        with open(get_abs_path("config/persona.yaml"), "r", encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}
        characters = config.get("characters", {})
        return [
            PersonaInfo(
                persona_id=str(values.get("slug") or name).strip().lower(),
                name=str(name),
                display_name=str(values.get("display_name") or name),
            )
            for name, values in characters.items()
        ]

    def require(self, persona_id: str) -> PersonaInfo:
        normalized = str(persona_id or "").strip().lower()
        for persona in self.list():
            if persona.persona_id == normalized:
                return persona
        raise ValueError(f"未知角色：{persona_id}")

    def id_for_name(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        for persona in self.list():
            if persona.name.lower() == normalized or persona.display_name.lower() == normalized:
                return persona.persona_id
        return normalized or "cyrene"


persona_catalog = PersonaCatalog()
