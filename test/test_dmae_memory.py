"""DMAE 分层记忆 + Worldbook + 用户画像 集成测试"""
import sys
sys.path.insert(0, r"d:\develop\PythonStudy\MutiRoleAgent")

from utils.config_handler import chroma_config

# ==================== L2 Worldbook 配置测试 ====================
print("=== L2 Worldbook 配置测试 ===")

# 新配置结构
assert "faq" in chroma_config, "缺少 faq 配置节"
assert "worldbook" in chroma_config, "缺少 worldbook 配置节"
assert chroma_config["faq"]["collection_name"] == "faq"
assert chroma_config["worldbook"]["collection_name"] == "worldbook"
print("✅ chroma.yaml 双 collection 配置正确")

# VectorStore 多 collection
from rag.vector_store import vector_store, COLLECTION_FAQ, COLLECTION_WORLDBOOK
store = vector_store._get_store(COLLECTION_FAQ)
assert store is not None
store2 = vector_store._get_store(COLLECTION_WORLDBOOK)
assert store2 is not None
assert store != store2, "两个 collection 应该是独立的 Chroma 实例"
print("✅ VectorStore faq/worldbook 独立实例正确")

# 检索器
retriever = vector_store.get_retriever(COLLECTION_FAQ)
assert retriever is not None
retriever_wb = vector_store.get_retriever(COLLECTION_WORLDBOOK)
assert retriever_wb is not None
print("✅ 两个 collection 检索器均可获取")

all_rets = vector_store.get_all_retrievers()
assert COLLECTION_FAQ in all_rets and COLLECTION_WORLDBOOK in all_rets
print("✅ get_all_retrievers() 正确")

# ==================== RAG 路由测试 ====================
print("\n=== RAG 路由测试 ===")

from rag.rag_service import _route_query

# FAQ 路由
r = _route_query("如何阅读项目文档")
assert r == ["faq"], f"期望 ['faq']，得到 {r}"
print("✅ 文档问题 → faq")

r = _route_query("请总结知识库资料")
assert r == ["faq"], f"期望 ['faq']，得到 {r}"
print("✅ 知识库问题 → faq")

# Worldbook 路由
r = _route_query("昔涟是谁")
assert r == ["worldbook"], f"期望 ['worldbook']，得到 {r}"
print("✅ 昔涟查询 → worldbook")

r = _route_query("尘歌壶的背景故事")
assert r == ["worldbook"], f"期望 ['worldbook']，得到 {r}"
print("✅ 世界观查询 → worldbook")

# 默认路由（无明确关键词 → faq）
r = _route_query("你好")
assert r == ["faq"], f"期望 ['faq']，得到 {r}"
print("✅ 无关键词默认 → faq")

# ==================== L0 用户画像测试 ====================
print("\n=== L0 用户画像测试 ===")

from memory.chat_db import chat_db
chat_db.init_db()

# 写入画像
chat_db.upsert_global_user_profile(
    "test_user_001",
    language="中文",
    occupation="软件工程师",
    stable_interests=["动漫", "Agent"],
    preferences={"回答风格": "简洁"},
)
print("✅ 用户画像写入成功")

# 读取画像
profile = chat_db.get_global_user_profile("test_user_001")
assert profile is not None
assert profile["occupation"] == "软件工程师"
print(f"✅ 用户画像读取成功: occupation={profile['occupation']}")

# 增量更新
chat_db.upsert_global_user_profile(
    "test_user_001",
    language="中文",
    occupation="软件工程师",
    stable_interests=["动漫", "Agent", "Python"],
    preferences={"回答风格": "简洁"},
)
profile2 = chat_db.get_global_user_profile("test_user_001")
assert "Python" in profile2["stable_interests"]
print(f"✅ 增量更新: interests={profile2['stable_interests']}")

# build_profile_context
from memory.user_profile_extractor import build_profile_context
ctx = build_profile_context("test_user_001")
assert "软件工程师" in ctx
assert "Python" in ctx
print(f"✅ 画像上下文生成: {ctx[:80]}...")

# ==================== L1 会话标题测试 ====================
print("\n=== L1 会话标题测试 ===")

chat_db.upsert_session_meta("test_session_001", title="项目文档咨询", user_id="test_user_001")
meta = chat_db.get_session_meta("test_session_001")
assert meta is not None
assert meta["title"] == "项目文档咨询"
print(f"✅ 会话标题写入/读取: {meta['title']}")

sessions = chat_db.list_sessions_with_meta(limit=5)
assert len(sessions) > 0
print(f"✅ 会话列表: {len(sessions)} 条")

# ==================== 清理测试数据 ====================
chat_db.clear_session("test_session_001")
print("\n✅ 测试数据已清理")

print("\n" + "=" * 40)
print("全部集成测试通过 ✅")
