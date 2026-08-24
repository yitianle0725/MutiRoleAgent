"""P3 checkpointer、summary 和 RunStore 离线测试。"""

import asyncio
import tempfile
from pathlib import Path

from agent.agent_state import create_agent_state
from agent.langgraph_adapter import build_graph_config
from agent.summary import build_history_summary
from orchestration.runs import RunStore


def test_summary_and_state_are_available():
    state = create_agent_state("当前问题", session_id="s1", agent_summary="历史摘要")
    assert state["agent_summary"] == "历史摘要"
    assert "当前问题" in build_history_summary(state["messages"])
    assert build_graph_config(session_id="s1")["configurable"]["thread_id"] == "s1"


def test_run_store_rebuilds_events():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(Path(directory))
            run = await store.create(session_id="s1", thread_id="t1", prompt="测试")
            await store.append_event(run.run_id, "run.status_changed", {
                "status": "completed", "steps": 2, "summary": "已完成"
            })
            restored = await store.get(run.run_id)
            assert restored is not None
            assert restored.status == "completed"
            assert restored.steps == 2
            assert restored.summary == "已完成"
            assert len(await store.read_events(run.run_id)) == 2

    asyncio.run(run())
