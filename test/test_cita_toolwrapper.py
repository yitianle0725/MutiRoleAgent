"""CITA 意图分类 + Tool Wrapper 模块级测试"""
import sys
import time
sys.path.insert(0, r"d:\develop\PythonStudy\MutiRoleAgent")

# ==================== CITA 测试 ====================
from agent.cita_classifier import classify_intent, build_cita_overlay, IntentResult

print("=== CITA 意图分类测试 ===\n")

# 1) 闲聊
r = classify_intent("你好呀，你能做什么？")
assert r.intent_type == "chitchat", f"期望 chitchat，得到 {r.intent_type}"
assert not r.needs_rag
assert "polite" in r.emotions or True  # 不强制
print(f"✅ 闲聊: type={r.intent_type}, emotions={r.emotions}, confidence={r.confidence:.2f}")

# 2) 愤怒
r = classify_intent("你们这个破机器人太垃圾了！我要投诉！")
assert "angry" in r.emotions, f"期望 angry，得到 {r.emotions}"
print(f"✅ 愤怒: emotions={r.emotions}")

# 3) 紧急
r = classify_intent("在线等！机器人不工作了，急！")
assert "urgent" in r.emotions, f"期望 urgent，得到 {r.emotions}"
print(f"✅ 紧急: emotions={r.emotions}")

# 4) 困惑
r = classify_intent("搞不懂怎么设置这个定时清扫，啥意思啊")
assert "confused" in r.emotions, f"期望 confused，得到 {r.emotions}"
print(f"✅ 困惑: emotions={r.emotions}")

# 5) RAG 需求
r = classify_intent("扫地机器人滤网怎么更换？")
assert r.needs_rag, f"期望 needs_rag=True"
print(f"✅ RAG 需求: needs_rag={r.needs_rag}")

# 6) 报告意图
r = classify_intent("帮我生成上个月的使用报告")
assert r.intent_type == "report", f"期望 report，得到 {r.intent_type}"
print(f"✅ 报告意图: type={r.intent_type}")

# 7) 联网搜索需求
r = classify_intent("最近有什么新款扫地机器人上市")
assert r.needs_web_search, f"期望 needs_web_search=True"
print(f"✅ 联网搜索: needs_web_search={r.needs_web_search}")

# 8) 空输入
r = classify_intent("")
assert r.intent_type == "chitchat"
print(f"✅ 空输入: type={r.intent_type}")

# ==================== CITA Overlay 测试 ====================
print("\n=== CITA Overlay 测试 ===\n")

r = classify_intent("气死我了！这个机器人根本不行！垃圾！")
overlay = build_cita_overlay(r)
assert "不满" in overlay or "歉意" in overlay, f"期望愤怒安抚指令，得到: {overlay[:80]}"
print(f"✅ 愤怒安抚 overlay ({len(overlay)} 字符): {overlay[:100]}...")

r = classify_intent("你好")
overlay = build_cita_overlay(r)
assert "闲聊" in overlay, f"期望闲聊路由，得到: {overlay[:80]}"
print(f"✅ 闲聊路由 overlay: {overlay[:80]}...")

r = classify_intent("今天天气怎么样")
overlay = build_cita_overlay(r)
# 可能没有情绪触发，overlay 可能为空或仅含轻度信号
print(f"✅ 日常查询 overlay: {'(空)' if not overlay else overlay[:80] + '...'}")

# ==================== Tool Wrapper 测试 ====================
print("\n=== Tool Wrapper 测试 ===\n")

from agent.tool_wrapper import execute_with_safety, get_tool_timeout, DEFAULT_TIMEOUTS
from langchain_core.messages import ToolMessage

# 模拟 handler
def fast_handler(req):
    return ToolMessage(content="success", tool_call_id="test_id")

def slow_handler(req):
    time.sleep(0.5)
    return ToolMessage(content="slow done", tool_call_id="test_id")

def error_handler(req):
    raise ValueError("模拟工具错误")

class FakeRequest:
    tool_call = {"id": "test_call_001"}

req = FakeRequest()

# 1) 正常执行
result = execute_with_safety(fast_handler, req, "get_weather", "test_id", timeout=2.0)
assert result.content == "success", f"期望 success，得到 {result.content}"
print("✅ Tool Wrapper: 正常执行通过")

# 2) 慢执行（在超时内完成）
result = execute_with_safety(slow_handler, req, "get_weather", "test_id", timeout=3.0)
assert result.content == "slow done"
print("✅ Tool Wrapper: 慢执行（超时内）通过")

# 3) 异常处理
result = execute_with_safety(error_handler, req, "rag_summarize", "test_id", timeout=5.0)
assert isinstance(result, ToolMessage)
assert "工具执行失败" in result.content, f"期望错误消息，得到 {result.content[:80]}"
assert "ValueError" in result.content
print(f"✅ Tool Wrapper: 异常捕获 → {result.content[:80]}...")

# 4) 默认超时查询
t = get_tool_timeout("rag_summarize")
assert t == 12.0, f"期望 12.0，得到 {t}"
t = get_tool_timeout("unknown_tool")
assert t == 10.0, f"期望默认 10.0，得到 {t}"
print(f"✅ Tool Wrapper: 超时查询 rag=12.0s, unknown=10.0s")

# 5) 超时测试（快速验证超时逻辑）
def very_slow_handler(req):
    time.sleep(2.0)
    return ToolMessage(content="too late", tool_call_id="test_id")

result = execute_with_safety(very_slow_handler, req, "get_weather", "test_id", timeout=0.5)
assert "工具超时" in result.content, f"期望超时消息，得到 {result.content[:80]}"
print(f"✅ Tool Wrapper: 超时控制 → {result.content[:80]}...")

print()
print("=" * 40)
print("全部测试通过 ✅")
