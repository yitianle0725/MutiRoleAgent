"""P1 编排边界离线测试。"""

import asyncio
import tempfile

from orchestration.coordinator import ConversationCoordinator
from orchestration.session_runner import SessionAgentRunner
from orchestration.runs import RunStore


class ForceAgentDecision:
    def evaluate(self, query, session_id="default", history=None):
        class Decision:
            is_chat = False
        return Decision()


class FakeAgent:
    async def execute_runtime_stream_async(self, prompt: str, *, run_context):
        yield run_context.event("run_started", {"runtime": "native"})
        yield run_context.event("tool_call_started", {
            "tool_call_id": "call-1",
            "tool_name": "fake_tool",
            "tool_args": {},
        })
        yield run_context.event("text_started", {"message_id": "message-1"})
        yield run_context.event("text_delta", {
            "message_id": "message-1",
            "text": f"回答：{prompt}",
        })
        yield run_context.event("text_finished", {
            "message_id": "message-1",
            "role": "answer",
            "text": f"回答：{prompt}",
        })
        yield run_context.event("run_finished", {"status": "completed"})


async def _factory(session_id: str, user_id: str | None, persona: str | None):
    return FakeAgent()


def test_coordinator_uses_runner_and_returns_result():
    async def run():
        coordinator = ConversationCoordinator(SessionAgentRunner(_factory), decision=ForceAgentDecision())
        result = await coordinator.handle_user_turn(
            "你好", session_id="session-1", persona="Cyrene"
        )
        assert result.response_text == "回答：你好"
        assert result.steps == 1
        assert result.role_name == "Cyrene"

    asyncio.run(run())


def test_runner_serializes_same_session():
    async def run():
        runner = SessionAgentRunner(_factory)
        outputs = []
        async for event in runner.stream("session-1", "测试"):
            if event.type == "final_text":
                outputs.append(str(event.data["text"]))
        assert outputs == ["回答：测试"]

    asyncio.run(run())


def test_coordinator_accepts_injected_dependencies_and_alias():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            coordinator = ConversationCoordinator(
                SessionAgentRunner(_factory), decision=ForceAgentDecision(), run_store=RunStore(directory)
            )
            events = []
            async for event in coordinator.handle_user_turn_stream("测试", session_id="s2"):
                events.append(event)
            assert events
            assert coordinator.session_id == "default"

    asyncio.run(run())
