"""离线验证主 FastAPI 应用的聊天流与任务管理使用同一个运行状态。"""

import asyncio
import json

import httpx
import pytest

from agent.harness_events import HarnessEvent
from channels.platforms import fastapi as channel
from evaluation.fastapi_load_test import _send_case
from memory.chat_db import ChatDB
from memory.session_store import SessionStore
from orchestration.context_builder import SessionContextBuilder
from orchestration.coordinator import ConversationCoordinator
from orchestration.runs import RunStore
from orchestration.session_runner import SessionAgentRunner


class OfflineExecutor:
    def __init__(self):
        self.run_id = None
        self.started = asyncio.Event()
        self.released = asyncio.Event()

    async def stream(self, prompt, context):
        if prompt == "timeout":
            raise TimeoutError("官方来源超时")
        if prompt == "slow":
            self.run_id = context.run_context.run_id
            self.started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.released.set()
        yield HarnessEvent(type="tool_start", data={"tool_name": "search_game_official"})
        yield HarnessEvent.final_text("官方活动：", delta=True)
        yield HarnessEvent.final_text("测试公告", delta=True)


class OfflineAck:
    async def delegated_ack(self, prompt, persona=None):
        return "已接收"


@pytest.fixture
def backend(tmp_path, monkeypatch):
    database = ChatDB(str(tmp_path / "chat.db"))
    database.init_db()
    session_store = SessionStore()
    executor = OfflineExecutor()
    store = RunStore(tmp_path / "runs")
    coordinator = ConversationCoordinator(
        SessionAgentRunner(lambda *_: None),
        roleplay=OfflineAck(),
        run_store=store,
        session_store=session_store,
        context_builder=SessionContextBuilder(database),
        chat_executor=executor,
        work_executor=executor,
    )
    monkeypatch.setattr(channel, "chat_db", database)
    monkeypatch.setattr("memory.session_store.session_store", session_store)
    app = channel._create_app()
    app.state.conversation_coordinator = coordinator
    return app, executor, store


def test_load_client_uses_main_routes_and_reads_terminal_event(backend):
    async def run():
        app, _, _ = backend
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            for question, status in [("official", "completed"), ("timeout", "failed")]:
                report = await _send_case(client, {"id": question, "query": question}, asyncio.Semaphore(1))
                assert report["status_code"] == 200
                assert report["run_status"] == status
                assert report["events"]["run_end"] == 1
                response = await client.get(f"/api/v1/runs/{report['run_id']}")
                assert response.json()["run"]["status"] == status
                if status == "completed":
                    assert report["answer"] == "官方活动：测试公告"
                    assert report["tool_names"] == ["search_game_official"]
                else:
                    assert "官方来源超时" in report["error"]
            assert (await client.get("/api/v1/sessions")).json() == []

    asyncio.run(run())


def test_cancel_and_retry_keep_the_same_terminal_status(backend):
    async def run():
        app, executor, store = backend
        coordinator = app.state.conversation_coordinator
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session = (await client.post("/api/v1/sessions", json={"mode": "work"})).json()
            streaming = asyncio.create_task(client.post("/api/v1/chat/stream", json={
                "session_id": session["session_id"], "message": "slow",
            }))
            await asyncio.wait_for(executor.started.wait(), timeout=5)
            cancelled = await client.post(f"/api/v1/runs/{executor.run_id}/cancel")
            assert cancelled.json()["run"]["status"] == "cancelled"
            response = await asyncio.wait_for(streaming, timeout=5)
            assert '"status": "cancelled"' in response.text
            assert executor.released.is_set()
            changes = [
                entry for entry in await store.read_events(executor.run_id)
                if entry["event"] == "run.status_changed"
            ]
            assert [entry["data"]["status"] for entry in changes] == ["cancelled"]

            failed = await coordinator.start_agent_turn("timeout", session_id=session["session_id"])
            await asyncio.wait_for(coordinator._tasks[failed.run_id], timeout=5)
            retried = await client.post(f"/api/v1/runs/{failed.run_id}/retry")
            run_id = retried.json()["result"]["run_id"]
            await asyncio.wait_for(coordinator._tasks[run_id], timeout=5)
            record = await store.get(run_id)
            assert record.status == "failed"
            assert record.retry_of_run_id == failed.run_id
            events = (await client.get(f"/api/v1/runs/{run_id}/events")).json()["events"]
            assert [record["data"]["status"] for record in events if record["event"] == "run.result"] == ["failed"]

    asyncio.run(run())


@pytest.mark.parametrize("send_stalled", [False, True])
def test_sse_disconnect_cancels_a_stalled_run(backend, send_stalled):
    async def run():
        app, executor, store = backend
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            session = (await client.post("/api/v1/sessions", json={"mode": "work"})).json()
        request_sent = False
        sending = asyncio.Event()
        payload = json.dumps({"session_id": session["session_id"], "message": "slow"}).encode()

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": payload}
            await executor.started.wait()
            if send_stalled:
                await sending.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if send_stalled and b"event: run_start" in message.get("body", b""):
                sending.set()
                await asyncio.Event().wait()

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "POST", "scheme": "http", "path": "/api/v1/chat/stream",
            "headers": [(b"content-type", b"application/json")], "query_string": b"",
        }
        await asyncio.wait_for(app(scope, receive, send), timeout=5)
        assert executor.released.is_set()
        record = await store.get(executor.run_id)
        assert record.status == "cancelled"
        events = await app.state.conversation_coordinator.get_run_events(executor.run_id)
        endings = [entry["data"] for entry in events if entry["data"].get("type") == "run_end"]
        assert [end["data"]["status"] for end in endings] == ["cancelled"]

    asyncio.run(run())
