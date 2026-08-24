"""P1 编排边界离线测试。"""

import asyncio

from agent.stream_events import TextChunk, ToolEvent
from orchestration.coordinator import ConversationCoordinator
from orchestration.session_runner import SessionAgentRunner


class FakeAgent:
    async def execute_stream_async(self, prompt: str):
        yield ToolEvent(phase="start", tool_name="fake_tool")
        yield TextChunk(content=f"回答：{prompt}")


async def _factory(session_id: str, user_id: str | None, persona: str | None):
    return FakeAgent()


def test_coordinator_uses_runner_and_returns_result():
    async def run():
        coordinator = ConversationCoordinator(SessionAgentRunner(_factory))
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
            if isinstance(event, TextChunk):
                outputs.append(event.content)
        assert outputs == ["回答：测试"]

    asyncio.run(run())
