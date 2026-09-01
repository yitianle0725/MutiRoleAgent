"""Native Runtime 是项目唯一 Agent 执行路径。"""

from pathlib import Path


def test_project_has_no_langgraph_runtime_or_dependency():
    root = Path(__file__).resolve().parents[1]

    assert not (root / "runtime" / "langgraph_runtime.py").exists()
    assert not (root / "agent" / "langgraph_adapter.py").exists()
    requirements = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "langgraph" not in requirements


def test_session_runner_has_no_runtime_switch():
    root = Path(__file__).resolve().parents[1]
    source = (root / "orchestration" / "session_runner.py").read_text(encoding="utf-8")

    assert "AGENT_RUNTIME" not in source
    assert "execute_runtime_stream_async" in source
