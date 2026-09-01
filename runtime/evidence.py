"""运行内证据账本。"""

from __future__ import annotations

from collections.abc import Iterable

from .tool_contracts import Evidence


class EvidenceLedger:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def add(self, evidence: Iterable[Evidence]) -> list[Evidence]:
        added: list[Evidence] = []
        for item in evidence:
            signature = (item.tool_name, item.source_url, repr(sorted(item.fields.items())))
            if any(
                (old.tool_name, old.source_url, repr(sorted(old.fields.items()))) == signature
                for old in self._items.values()
            ):
                continue
            self._items[item.evidence_id] = item
            added.append(item)
        return added

    @property
    def items(self) -> tuple[Evidence, ...]:
        return tuple(self._items.values())

    def urls(self) -> set[str]:
        return {item.source_url for item in self._items.values() if item.source_url}

    def prompt_block(self) -> str:
        if not self._items:
            return "当前没有通过验证的工具证据。"
        lines = ["以下是 Runtime 已验证并允许引用的证据："]
        for item in self._items.values():
            lines.append(
                f"- [{item.evidence_id}] fields={item.fields!r}; "
                f"url={item.source_url or '无'}; published_at={item.published_at or '未知'}; "
                f"trust={item.trust_level}"
            )
        lines.append("只能使用以上事实和 URL；缺失信息必须明确说无法确认。")
        return "\n".join(lines)
