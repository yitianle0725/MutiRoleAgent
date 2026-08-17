"""运行追踪与监控存储的轻量集成测试。"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from observability.store import MonitorStore
from utils.conversation_tracer import ConversationTracer
from eval.agent_metrics import latency_metrics


def test_monitor_store_persists_trace() -> None:
    """后台写入后可以查询轮次和事件。"""
    with tempfile.TemporaryDirectory() as directory:
        store = MonitorStore(Path(directory) / "monitor.db")
        tracer = ConversationTracer("test-session", "trace-test")
        tracer.enter("测试请求")
        tracer.decision("chat", 0.9, "test")
        tracer.exit()
        store.enqueue_turn(
            {
                "trace_id": "trace-test",
                "session_id": "test-session",
                "route": "chat",
                "outcome": "success",
                "duration_ms": 12.0,
                "ttft_ms": 3.0,
                "input_tokens": 10,
                "output_tokens": 5,
                "tool_calls": 0,
                "events": tracer.export_events(),
            }
        )

        for _ in range(20):
            trace = store.get_trace("trace-test")
            if trace is not None:
                break
            time.sleep(0.05)

        assert trace is not None
        assert trace["route"] == "chat"
        assert len(trace["events"]) == 3
        store.close()


def test_latency_metrics_uses_nearest_rank_p95() -> None:
    result = latency_metrics([{"duration_ms": value} for value in range(1, 21)])
    assert result["p95_ms"] == 19


if __name__ == "__main__":
    test_monitor_store_persists_trace()
    print("observability test passed")
