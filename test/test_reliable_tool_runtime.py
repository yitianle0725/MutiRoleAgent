"""可信工具调用内核的离线回归测试。"""

import asyncio
import json

from langchain_core.tools import tool

from runtime.answer_guard import AnswerValidator, AnswerabilityGate
from runtime.context import RunContext
from runtime.evidence import EvidenceLedger
from runtime.result_validator import ResultValidator
from runtime.tool_contracts import ToolRequirement
from runtime.tool_policy import ToolPolicy
from runtime.tool_scheduler import ToolScheduler


def test_fresh_official_request_requires_evidence():
    requirement = ToolPolicy().evaluate(
        "今天米游社有什么新的官方公告 URL？",
        {"search_game_official", "web_search"},
    )

    assert requirement.evidence_required is True
    assert requirement.freshness_required is True
    assert requirement.official_only is True
    assert requirement.required_fields == ("title", "url", "published_at")
    assert requirement.preferred_tools[0] == "search_game_official"


def test_official_validator_keeps_title_and_url_in_same_evidence():
    content = json.dumps({
        "articles": [{
            "title": "测试公告",
            "url": "https://www.miyoushe.com/ys/article/123",
            "published_at": "2026-09-01",
        }]
    }, ensure_ascii=False)

    quality, _, evidence, _, error = ResultValidator().validate(
        "search_game_official", content, official_only=True,
    )

    assert quality == "valid"
    assert error is None
    assert len(evidence) == 1
    assert evidence[0].fields["title"] == "测试公告"
    assert evidence[0].source_url.endswith("/123")
    assert evidence[0].trust_level == "official"


def test_unofficial_result_is_rejected_for_official_request():
    content = json.dumps({
        "results": [{"title": "转载", "url": "https://example.com/post/1"}]
    }, ensure_ascii=False)

    quality, _, evidence, _, _ = ResultValidator().validate(
        "web_search", content, official_only=True,
    )

    assert quality == "source_mismatch"
    assert evidence == ()


def test_answer_validator_rejects_unsupported_url():
    validator = ResultValidator()
    _, _, evidence, _, _ = validator.validate(
        "search_game_official",
        json.dumps({
            "articles": [{
                "title": "公告",
                "url": "https://www.miyoushe.com/ys/article/123",
            }]
        }, ensure_ascii=False),
        official_only=True,
    )
    ledger = EvidenceLedger()
    ledger.add(evidence)
    requirement = ToolRequirement(evidence_required=True, official_only=True)

    valid, errors = AnswerValidator().validate(
        "公告：https://www.miyoushe.com/ys/article/999",
        requirement,
        ledger,
    )

    assert valid is False
    assert "未被工具证据支持" in errors[0]


def test_answerability_rejects_empty_evidence():
    decision = AnswerabilityGate().evaluate(
        ToolRequirement(evidence_required=True),
        EvidenceLedger(),
    )
    assert decision.status == "not_answerable"


@tool
async def empty_search(query: str) -> str:
    """Return an empty structured search result."""
    return json.dumps({"query": query, "results": []}, ensure_ascii=False)


def test_scheduler_separates_execution_success_from_empty_quality():
    async def run():
        scheduler = ToolScheduler([empty_search])
        return await scheduler.execute(
            {"id": "call-1", "name": "empty_search", "args": {"query": "公告"}},
            requirement=ToolRequirement(allowed_tools=("empty_search",)),
            context=RunContext(session_id="s1"),
        )

    result = asyncio.run(run())
    assert result.execution_status == "completed"
    assert result.quality_status == "empty"
    assert result.fallback_required is True


@tool
async def slow_search(query: str) -> str:
    """Wait long enough for cooperative cancellation."""
    await asyncio.sleep(5)
    return query


def test_scheduler_cancels_running_tool_immediately():
    async def run():
        context = RunContext(session_id="s1")
        scheduler = ToolScheduler([slow_search], timeout_seconds=10)
        task = asyncio.create_task(scheduler.execute(
            {"id": "call-1", "name": "slow_search", "args": {"query": "公告"}},
            requirement=ToolRequirement(allowed_tools=("slow_search",)),
            context=context,
        ))
        await asyncio.sleep(0.01)
        context.cancel()
        return await asyncio.wait_for(task, timeout=1)

    result = asyncio.run(run())
    assert result.execution_status == "cancelled"


def test_official_request_rejects_homepage_only_result():
    quality, _, evidence, _, _ = ResultValidator().validate(
        "web_search",
        json.dumps({
            "results": [{"title": "官网", "url": "https://www.miyoushe.com/"}]
        }, ensure_ascii=False),
        official_only=True,
    )
    assert quality == "source_mismatch"
    assert evidence == ()
