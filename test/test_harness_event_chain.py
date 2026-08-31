from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage

from agent.harness_events import HarnessEvent
from agent.react_agent import classify_ai_content
from agent.structured_output.validator import remove_extracted_json
from channels.platforms.fastapi import harness_event_sse_message
from memory.chat_db import ChatDB
from memory.session_store import SessionStore
from orchestration.context_builder import SessionContextBuilder
from orchestration.coordinator import ConversationCoordinator
from orchestration.finish_hook import TurnFinishHook


class _UnusedRunner:
    _session_store = None
    _run_store = None


class _HarnessExecutor:
    async def stream(self, prompt, context):
        yield HarnessEvent.process_text("我先查一下")
        yield HarnessEvent.tool_start(
            tool_call_id="call-1",
            tool_name="search_anime",
            tool_args={"query": prompt},
        )
        yield HarnessEvent.tool_end(
            tool_call_id="call-1",
            tool_name="search_anime",
            result_preview="工具结果",
        )
        yield HarnessEvent.structured_data(
            schema_type="anime_recommendation",
            data={"items": []},
        )
        yield HarnessEvent.final_text("这是正式答案")


def test_tool_call_content_is_never_final_text():
    process = AIMessage(
        content="我先查询",
        tool_calls=[{"id": "call-1", "name": "search_anime", "args": {}}],
    )
    final = AIMessage(content="查询完成", tool_calls=[])

    assert classify_ai_content(process) == "process_text"
    assert classify_ai_content(final) == "final_text"


def test_structured_json_is_removed_from_final_text():
    response = '查到啦。\n\n```json\n{"items": []}\n```'
    assert remove_extracted_json(response) == "查到啦。"


def test_history_only_persists_user_and_final_text(tmp_path, monkeypatch):
    database = ChatDB(str(tmp_path / "chat.db"))
    database.init_db()
    database.create_session(
        "session-1",
        user_id="user-1",
        persona_id="cyrene",
        mode="work",
    )
    session_store = SessionStore()

    monkeypatch.setattr(
        "orchestration.finish_hook.schedule_profile_extraction",
        lambda *args, **kwargs: None,
    )
    executor = _HarnessExecutor()
    coordinator = ConversationCoordinator(
        _UnusedRunner(),
        context_builder=SessionContextBuilder(database),
        chat_executor=executor,
        work_executor=executor,
        finish_hook=TurnFinishHook(database, session_store),
    )

    async def collect():
        return [
            event
            async for event in coordinator.stream_user_turn(
                "推荐一部番剧",
                session_id="session-1",
            )
        ]

    events = asyncio.run(collect())
    assert [event.type for event in events] == [
        "run_start",
        "process_text",
        "tool_start",
        "tool_end",
        "structured_data",
        "final_text",
        "run_end",
    ]
    assert [event.sequence for event in events] == list(range(1, 8))
    assert len({event.run_id for event in events}) == 1
    history = database.get_history_raw("session-1")
    assert [(item["role"], item["content"]) for item in history] == [
        ("user", "推荐一部番剧"),
        ("assistant", "这是正式答案"),
    ]


def test_sse_and_websocket_share_the_same_envelope():
    event = HarnessEvent.final_text("完成").bind(run_id="run-1", sequence=2)
    message = harness_event_sse_message(event)

    assert message["event"] == "final_text"
    assert json.loads(message["data"]) == event.to_dict()
