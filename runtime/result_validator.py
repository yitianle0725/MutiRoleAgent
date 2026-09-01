"""把任意工具输出规范化，并抽取可追溯证据。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .tool_contracts import Evidence, QualityStatus


_ERROR_KEYS = {"error", "errors", "exception"}
_EMPTY_KEYS = {"results", "articles", "items", "data"}
_OFFICIAL_DOMAINS = {
    "miyoushe.com", "www.miyoushe.com", "hoyolab.com", "www.hoyolab.com",
    "mihoyo.com", "www.mihoyo.com", "hoyoverse.com", "www.hoyoverse.com",
}
_URL_PATTERN = re.compile(r"https?://[^\s\]\[<>()\"']+")


class ResultValidator:
    def parse(self, content: str) -> Any:
        text = str(content or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def validate(
        self,
        tool_name: str,
        content: str,
        *,
        official_only: bool = False,
    ) -> tuple[QualityStatus, Any, tuple[Evidence, ...], bool, str | None]:
        data = self.parse(content)
        if data is None:
            return "empty", data, (), False, "工具没有返回内容"
        if isinstance(data, dict):
            error = next((data.get(key) for key in _ERROR_KEYS if data.get(key)), None)
            fallback = bool(data.get("websearch_fallback_required") or data.get("fallback_required"))
            if self._is_empty_mapping(data):
                return "empty", data, (), fallback, str(error or "没有检索到结果")
            if error and not self._has_nonempty_collection(data):
                return "unverified", data, (), fallback, str(error)
        else:
            fallback = False
            lowered = str(data).lower()
            if any(word in lowered for word in ("执行失败", "查询失败", "timeout", "error:")):
                return "unverified", data, (), False, str(data)[:300]

        evidence = tuple(self._extract_evidence(tool_name, data, official_only=official_only))
        if official_only and not any(item.trust_level == "official" for item in evidence):
            return "source_mismatch", data, (), fallback, "结果没有提供可验证的官方文章页"
        if evidence:
            return "valid", data, evidence, fallback, None
        # 本地动作型工具不一定产生 URL，仍可作为字段证据使用。
        fields = data if isinstance(data, dict) else {"result": str(data)}
        generic = Evidence(
            evidence_id=f"ev_{uuid.uuid4().hex[:10]}",
            tool_name=tool_name,
            fields=fields,
            trust_level="tool",
        )
        return "partial", data, (generic,), fallback, None

    def _extract_evidence(
        self,
        tool_name: str,
        value: Any,
        *,
        official_only: bool,
    ) -> list[Evidence]:
        output: list[Evidence] = []
        for record in self._records(value):
            url = self._first_url(record)
            if not url:
                continue
            domain = urlparse(url).netloc.lower()
            path = urlparse(url).path.strip("/")
            is_official = domain in _OFFICIAL_DOMAINS or any(
                domain.endswith(f".{allowed}") for allowed in _OFFICIAL_DOMAINS
            )
            if official_only and not is_official:
                continue
            if official_only and not path:
                # 官网首页不能证明某一篇公告的标题和发布时间。
                continue
            published = self._first(record, "published_at", "publish_time", "date", "time")
            output.append(Evidence(
                evidence_id=f"ev_{uuid.uuid4().hex[:10]}",
                tool_name=tool_name,
                source_url=url,
                source_domain=domain,
                source_type="official_article" if is_official else "web_result",
                published_at=str(published) if published else None,
                fields=self._useful_fields(record),
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                trust_level="official" if is_official else "external",
            ))
        return output

    def _records(self, value: Any):
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    yield from self._records(nested)
        elif isinstance(value, list):
            for item in value:
                yield from self._records(item)

    def _first_url(self, record: dict[str, Any]) -> str | None:
        for key in ("url", "link", "article_url", "source_url"):
            value = record.get(key)
            if isinstance(value, str):
                match = _URL_PATTERN.search(value)
                if match:
                    return match.group(0).rstrip(".,;，。；")
        return None

    @staticmethod
    def _first(record: dict[str, Any], *keys: str) -> Any:
        return next((record.get(key) for key in keys if record.get(key) not in (None, "")), None)

    def _useful_fields(self, record: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "title", "name", "summary", "snippet", "description", "game", "city",
            "weather", "temperature", "temperature_high", "temperature_low",
            "forecast_date", "published_at", "publish_time", "date", "time", "url", "link",
        )
        fields = {key: record[key] for key in keys if record.get(key) not in (None, "", [], {})}
        return fields or {key: value for key, value in list(record.items())[:12] if not isinstance(value, (dict, list))}

    @staticmethod
    def _is_empty_mapping(data: dict[str, Any]) -> bool:
        present = [data[key] for key in _EMPTY_KEYS if key in data]
        return bool(present) and all(value in (None, "", [], {}) for value in present)

    @staticmethod
    def _has_nonempty_collection(data: dict[str, Any]) -> bool:
        return any(data.get(key) not in (None, "", [], {}) for key in _EMPTY_KEYS if key in data)
