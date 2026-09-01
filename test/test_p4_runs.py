"""P4 运行生命周期测试。"""

import asyncio
import tempfile
from pathlib import Path

from orchestration.coordinator import ConversationCoordinator
from orchestration.runs import RunStore
from orchestration.session_runner import SessionAgentRunner
from orchestration.roleplay import RoleplayEngine


class SlowAgent:
    async def execute_runtime_stream_async(self, prompt: str, *, run_context):
        yield run_context.event("run_started", {"runtime": "native"})
        yield run_context.event("text_started", {"message_id": "message-1"})
        yield run_context.event("text_delta", {
            "message_id": "message-1", "text": f"结果：{prompt}",
        })
        yield run_context.event("text_finished", {
            "message_id": "message-1", "role": "answer", "text": f"结果：{prompt}",
        })
        await asyncio.sleep(0.2)
        yield run_context.event("run_finished", {"status": "completed"})


async def factory(session_id, user_id, persona):
    return SlowAgent()


class AckModel:
    async def ainvoke(self, messages, **kwargs):
        class Response:
            content = "好的，我来处理。"
        return Response()


def test_two_phase_completion_and_query():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            coordinator = ConversationCoordinator(
                SessionAgentRunner(factory), RoleplayEngine(model=AckModel()), RunStore(Path(directory))
            )
            immediate = await coordinator.start_agent_turn("查询", session_id="s1")
            assert immediate.delegated is True
            assert immediate.completed is False
            assert immediate.run_id
            await asyncio.sleep(0.3)
            run_state = await coordinator.get_run(immediate.run_id)
            assert run_state is not None
            assert run_state.status == "completed"

    asyncio.run(run())


def test_cancel_and_request_input():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            coordinator = ConversationCoordinator(
                SessionAgentRunner(factory), RoleplayEngine(model=AckModel()), RunStore(Path(directory))
            )
            immediate = await coordinator.start_agent_turn("长任务", session_id="s1")
            cancelled = await coordinator.cancel_run(immediate.run_id)
            assert cancelled is not None
            assert cancelled.status == "cancelled"

            waiting = await coordinator.request_user_input(
                immediate.run_id, "请选择游戏", options=["原神", "星铁"]
            )
            # 已取消任务不能覆盖为 waiting 状态，状态机保持终态。
            assert waiting is not None
            assert waiting.status == "cancelled"

    asyncio.run(run())


def test_waiting_run_recovers_as_linked_replay():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(Path(directory))
            original = await store.create(
                session_id="s1", thread_id="s1", prompt="查询天气",
            )
            await store.set_status(
                original.run_id,
                "waiting_for_input",
                pending_user_input={"field": "city", "question": "哪个城市？"},
            )
            coordinator = ConversationCoordinator(
                SessionAgentRunner(factory), RoleplayEngine(model=AckModel()), store,
            )
            resumed = await coordinator.resume_agent_run(original.run_id, "广州")
            recovered = await store.get(resumed.run_id)
            previous = await store.get(original.run_id)

            assert resumed.run_id != original.run_id
            assert recovered is not None
            assert recovered.retry_of_run_id == original.run_id
            assert "广州" in recovered.prompt
            assert previous is not None and previous.status == "failed"

    asyncio.run(run())
