"""P2 角色层与事实表达测试。"""

import asyncio

from agent.results import AgentFactResult
from orchestration.roleplay import RoleplayEngine


class FakeResponse:
    content = "角色化结果"


class FakeModel:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages, **kwargs):
        self.calls.append(messages)
        return FakeResponse()


def test_roleplay_only_receives_facts():
    async def run():
        model = FakeModel()
        engine = RoleplayEngine(model=model)
        fact = AgentFactResult(status="completed", text="工具返回：活动 URL=https://example.com")
        result = await engine.present_agent_result(fact, persona="Cyrene")
        assert result == "角色化结果"
        assert "活动 URL" in str(model.calls[0][-1].content)

    asyncio.run(run())


def test_failed_fact_falls_back_without_fabricating_success():
    async def run():
        engine = RoleplayEngine(model=None)
        fact = AgentFactResult(status="failed", errors=["网络超时"])
        result = await engine.present_agent_result(fact)
        assert "失败" in result
        assert "网络超时" in result
        assert "成功" not in result

    asyncio.run(run())


def test_waiting_input_keeps_original_question():
    async def run():
        engine = RoleplayEngine(model=FakeModel())
        result = await engine.present_user_input_request("请选择游戏：原神/星铁")
        assert result.endswith("请选择游戏：原神/星铁")

    asyncio.run(run())
