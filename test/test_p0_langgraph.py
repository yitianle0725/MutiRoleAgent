"""P0 LangGraph 状态与统一 DTO 的离线测试。"""

from agent.content import ContentBlock, content_to_text, normalize_content, text_content
from agent.langgraph_adapter import build_graph_config
from agent.results import AgentFactResult
from agent.agent_state import create_agent_state
from agent.request import AgentRequest
from agent.stream_events import StructuredData, TextChunk, ToolEvent, event_to_content_block


def test_content_blocks_preserve_text_and_attachment():
    content = [
        text_content("已完成"),
        ContentBlock(type="file", data="report.json"),
    ]
    assert content_to_text(content) == "已完成"
    assert len(normalize_content(content)) == 2


def test_agent_state_has_thread_and_fact_fields():
    state = create_agent_state("查询原神活动", session_id="s1", thread_id="t1")
    assert state["thread_id"] == "t1"
    assert state["facts"] == []
    assert state["errors"] == []


def test_graph_config_separates_thread_and_run():
    config = build_graph_config(session_id="s1", thread_id="t1", run_id="r1")
    assert config["configurable"]["thread_id"] == "t1"
    assert config["configurable"]["run_id"] == "r1"
    assert config["metadata"]["session_id"] == "s1"


def test_fact_result_does_not_treat_errors_as_success():
    result = AgentFactResult(status="completed", text="结果", errors=["工具失败"])
    assert not result.ok


def test_agent_request_normalizes_runtime_fields():
    request = AgentRequest(session_id="s1", prompt=" 查询 ", max_steps=0, timeout_seconds=0)
    assert request.prompt == "查询"
    assert request.thread_id == "s1"
    assert request.max_steps == 1
    assert request.timeout_seconds == 1.0


def test_stream_events_convert_to_content_blocks():
    assert event_to_content_block(TextChunk("文本")).type == "text"
    assert event_to_content_block(ToolEvent("start", "search")).type == "json"
    structured = StructuredData("demo", object(), "", {"ok": True})
    assert event_to_content_block(structured).metadata["schema_type"] == "demo"
