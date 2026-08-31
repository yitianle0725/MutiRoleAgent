from __future__ import annotations

import asyncio
import sqlite3

from agent.harness_events import HarnessEvent
from memory.chat_db import ChatDB
from orchestration.context_builder import SessionContextBuilder
from orchestration.coordinator import ConversationCoordinator


class _UnusedRunner:
    _session_store = None
    _run_store = None


class _RecordingExecutor:
    def __init__(self, label: str) -> None:
        self.label = label
        self.contexts = []

    async def stream(self, prompt, context):
        self.contexts.append(context)
        yield HarnessEvent.final_text(f"{self.label}:{prompt}")


class _FinishHook:
    async def complete(self, **kwargs):
        return None


def _database(tmp_path) -> ChatDB:
    database = ChatDB(str(tmp_path / "chat.db"))
    database.init_db()
    return database


def test_session_binding_is_immutable_and_allows_duplicate_combinations(tmp_path):
    database = _database(tmp_path)
    first = database.create_session(
        "session-a", user_id="user1", persona_id="cyrene", mode="chat"
    )
    second = database.create_session(
        "session-b", user_id="user1", persona_id="cyrene", mode="chat"
    )
    database.init_db()

    assert first["persona_id"] == second["persona_id"] == "cyrene"
    assert database.get_session("session-a") is not None
    assert first["mode"] == second["mode"] == "chat"
    assert first["session_id"] != second["session_id"]


def test_persona_memories_do_not_leak_between_personas(tmp_path):
    database = _database(tmp_path)
    database.create_session(
        "cyrene-chat", user_id="user1", persona_id="cyrene", mode="chat"
    )
    database.create_session(
        "columbina-chat", user_id="user1", persona_id="columbina", mode="chat"
    )
    database.add_memory(
        scope="user_global", user_id="user1", content="用户叫天乐"
    )
    database.add_memory(
        scope="user_persona",
        user_id="user1",
        persona_id="cyrene",
        content="约定周末看电影",
    )

    cyrene = database.list_scoped_memories(database.require_session("cyrene-chat"))
    columbina = database.list_scoped_memories(database.require_session("columbina-chat"))

    assert cyrene["user_global"] == columbina["user_global"] == ["用户叫天乐"]
    assert cyrene["user_persona"] == ["约定周末看电影"]
    assert columbina["user_persona"] == []


def test_legacy_sessions_are_migrated_idempotently(tmp_path):
    database = _database(tmp_path)
    with sqlite3.connect(str(tmp_path / "chat.db")) as connection:
        connection.execute(
            "INSERT INTO session_meta(session_id, title, user_id) VALUES('legacy', '旧会话', '')"
        )
        connection.execute(
            "INSERT INTO chat_history(session_id, role, content) VALUES('legacy', 'user', '你好')"
        )
    database.init_db()
    database.init_db()

    session = database.get_session("legacy")
    assert session is not None
    assert session["user_id"] == "local_user"
    assert session["persona_id"] == "cyrene"
    assert session["mode"] == "chat"
    assert database.get_history_raw("legacy")[0]["content"] == "你好"


def test_coordinator_routes_only_by_locked_session_mode(tmp_path):
    database = _database(tmp_path)
    database.create_session(
        "chat-session", user_id="user1", persona_id="cyrene", mode="chat"
    )
    database.create_session(
        "work-session", user_id="user1", persona_id="cyrene", mode="work"
    )
    chat = _RecordingExecutor("chat")
    work = _RecordingExecutor("work")
    coordinator = ConversationCoordinator(
        _UnusedRunner(),
        context_builder=SessionContextBuilder(database),
        chat_executor=chat,
        work_executor=work,
        finish_hook=_FinishHook(),
    )

    async def collect(session_id: str) -> str:
        chunks = []
        async for event in coordinator.stream_user_turn(
            "搜索最新资讯", session_id=session_id
        ):
            if event.type == "final_text":
                chunks.append(str(event.data["text"]))
        return "".join(chunks)

    assert asyncio.run(collect("chat-session")) == "chat:搜索最新资讯"
    assert asyncio.run(collect("work-session")) == "work:搜索最新资讯"
    assert len(chat.contexts) == 1
    assert len(work.contexts) == 1
