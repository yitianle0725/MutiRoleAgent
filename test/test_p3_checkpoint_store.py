"""项目 checkpoint 不依赖图框架。"""

import asyncio

from agent.checkpoint import AgentCheckpoint, CheckpointStore


def test_checkpoint_round_trip(tmp_path):
    async def run():
        store = CheckpointStore(tmp_path)
        checkpoint = AgentCheckpoint(
            run_id="run-1",
            session_id="session-1",
            thread_id="session-1",
            step=2,
            tool_calls=[{"tool": "search"}],
        )
        await store.save(checkpoint)
        return await store.latest("run-1")

    restored = asyncio.run(run())
    assert restored is not None
    assert restored.step == 2
    assert restored.tool_calls == [{"tool": "search"}]
