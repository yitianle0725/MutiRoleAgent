"""Action Gate + Execution Policy 模块级测试"""
import sys
sys.path.insert(0, r"d:\develop\PythonStudy\MutiRoleAgent")

from agent.action_gate import action_gate, GateResult
print("1/7 action_gate 导入 OK")

from agent.execution_policy import validate_tool_args, PolicyResult, TOOL_SCHEMAS
print(f"2/7 execution_policy 导入 OK ({len(TOOL_SCHEMAS)} 个 Schema)")

# ==================== Gate 测试 ====================
r = action_gate.check_tool_call("rag_summarize", {"query": "test"})
assert r.allow, f"安全工具被拦截: {r.reason}"
print("3/7 Gate: 安全工具 → 放行 ✓")

r = action_gate.check_tool_call("delete_files", {})
assert not r.allow, "危险工具未被拦截"
print("4/7 Gate: 危险工具名 → 拒绝 ✓")

r = action_gate.check_tool_call("rag_summarize", {"query": "../../etc/passwd"})
assert not r.allow, "路径穿越未被拦截"
print("5/7 Gate: 路径穿越 → 拒绝 ✓")

# ==================== Policy 测试 ====================
r = validate_tool_args("rag_summarize", {"query": ""})
assert not r.valid, "空 query 未被拦截"
print(f"6/7 Policy: 空 query → 拒绝 ({r.error_message[:40]}) ✓")

r = validate_tool_args("rag_summarize", {"query": "扫地机器人保养"})
assert r.valid, f"有效 query 被拒绝: {r.error_message}"
print("7/7 Policy: 有效 query → 通过 ✓")

r = validate_tool_args("fetch_external_data", {"user_id": "1001", "month": "2025-06"})
assert r.valid, f"有效 fetch 被拒绝: {r.error_message}"
print("8/7 Policy: fetch_external_data 正确 → 通过 ✓")

r = validate_tool_args("fetch_external_data", {"user_id": "abc", "month": "202506"})
assert not r.valid, "无效 fetch 未被拦截"
print(f"9/7 Policy: fetch 错误格式 → 拒绝 ✓")

r = validate_tool_args("get_user_location", {})
assert r.valid, "无参工具被拒绝"
print("10/7 Policy: 无参工具 → 宽松通过 ✓")

r = validate_tool_args("unknown_tool", {"key": "val"})
assert r.valid, "未知工具被拒绝"
print("11/7 Policy: 未知工具 → 宽松通过 ✓")

print()
print("=" * 40)
print("全部测试通过 ✅")
