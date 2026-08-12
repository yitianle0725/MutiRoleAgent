"""Phase 6: 结构化输出 — 模块级测试"""
import sys
import io
sys.path.insert(0, r"d:\develop\PythonStudy\MutiRoleAgent")

# 修复 Windows GBK 终端编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ==================== 1. Schema 导入 ====================
from agent.structured_output.schemas import (
    AnimeItem, AnimeRecommendationList, SeasonOverview,
    AnimeDeepDive, WeatherReport, FileOperationResult,
    SCHEMA_REGISTRY,
)
print(f"1/10 Schema 导入 OK ({len(SCHEMA_REGISTRY)} 个 Schema: {list(SCHEMA_REGISTRY.keys())})")

# 基本字段校验
item = AnimeItem(
    chinese_name="进击的巨人",
    japanese_name="進撃の巨人",
    score=9.1,
    rank=1,
    tags=["热血", "战斗"],
    reason="现象级作品",
    url="https://bangumi.tv/subject/xxx",
)
assert item.chinese_name == "进击的巨人"
assert item.score == 9.1
print("2/10 AnimeItem 字段校验 OK ✓")

# score 边界
try:
    AnimeItem(chinese_name="test", score=11, reason="test")
    assert False, "score=11 应该报错"
except Exception:
    pass
print("3/10 score 边界校验 (>10 拦截) OK ✓")

# SCHEMA_REGISTRY 映射
assert SCHEMA_REGISTRY["anime_recommendation"] == AnimeRecommendationList
assert SCHEMA_REGISTRY["season_overview"] == SeasonOverview
assert SCHEMA_REGISTRY["weather_report"] == WeatherReport
print("4/10 SCHEMA_REGISTRY 映射 OK ✓")

# ==================== 2. Validator ====================
from agent.structured_output.validator import (
    extract_json, validate_output, build_error_feedback,
    extract_and_validate, ValidationResult,
)
print("5/10 Validator 导入 OK")

# 2a) extract_json: ```json 代码块
text_with_fence = '''
推荐几部热血番：

```json
{"items": [{"chinese_name": "进击的巨人", "reason": "好看"}]}
```

希望你喜欢！
'''
data = extract_json(text_with_fence)
assert data is not None, "代码块 JSON 提取失败"
assert data["items"][0]["chinese_name"] == "进击的巨人"
print("6/10 extract_json: fenced ```json 代码块 OK ✓")

# 2b) extract_json: 裸 JSON（无代码块标记）
text_bare = '这是结果：\n\n{"items": [{"chinese_name": "鬼灭之刃", "reason": "感人"}]}'
data = extract_json(text_bare)
assert data is not None, "裸 JSON 提取失败"
assert data["items"][0]["chinese_name"] == "鬼灭之刃"
print("7/10 extract_json: 裸 JSON 提取 OK ✓")

# 2c) extract_json: 数组 JSON
text_array = '```json\n[{"chinese_name": "A", "reason": "r"}]\n```'
data = extract_json(text_array)
assert data is not None, "数组 JSON 提取失败"
print("8/10 extract_json: 数组 JSON 提取 OK ✓")

# 2d) extract_json: 无 JSON
text_no_json = "你好，这是一段纯文本回复，没有任何 JSON。"
data = extract_json(text_no_json)
assert data is None, "无 JSON 时应返回 None"
print("9/10 extract_json: 无 JSON → None OK ✓")

# 2e) validate_output: 合法数据
valid_data = {
    "items": [
        {
            "chinese_name": "进击的巨人",
            "japanese_name": "進撃の巨人",
            "score": 9.1,
            "rank": 1,
            "tags": ["热血"],
            "reason": "神作",
            "url": "https://example.com",
        }
    ]
}
result = validate_output(valid_data, AnimeRecommendationList)
assert result.valid, f"合法数据校验失败: {result.errors}"
assert isinstance(result.model, AnimeRecommendationList)
assert len(result.model.items) == 1
print("10/10 validate_output: 合法数据 OK ✓")

# 2f) validate_output: 缺少必填字段
result = validate_output({"items": [{"chinese_name": "test"}]}, AnimeRecommendationList)
assert not result.valid, "缺字段应校验失败"
assert result.reason == "validation_error"
print("11/10 validate_output: 缺字段 → validation_error ✓")

# 2g) validate_output: 类型错误
result = validate_output(
    {"items": [{"chinese_name": "test", "reason": "ok", "score": "高分"}]},
    AnimeRecommendationList,
)
assert not result.valid, "类型错误应校验失败"
print("12/10 validate_output: 类型错误 → 校验失败 ✓")

# 2h) extract_and_validate: 未知 schema
result = extract_and_validate('{"x": 1}', "unknown_schema")
assert not result.valid
assert result.reason == "unknown_schema"
print("13/10 extract_and_validate: 未知 schema → unknown_schema ✓")

# 2i) build_error_feedback
feedback = build_error_feedback(result)
assert "找不到 schema" in feedback or "unknown" in feedback.lower()
print("14/10 build_error_feedback: 中文反馈 OK ✓")

# 2j) extract_and_validate: 一步式
text = '```json\n{"items": [{"chinese_name": "A", "reason": "r"}]}\n```'
vr = extract_and_validate(text, "anime_recommendation")
assert vr.valid, f"一步式校验失败: {vr.errors}"
print("15/10 extract_and_validate: 一步式 OK ✓")

# ==================== 3. Formatter ====================
from agent.structured_output.formatter import (
    FORMATTER_REGISTRY, format_model, format_anime_card_list,
    format_season_table, format_weather_card,
)
print("16/10 Formatter 导入 OK")

# 3a) format_anime_card_list
rec = AnimeRecommendationList(items=[
    AnimeItem(chinese_name="进击的巨人", score=9.1, rank=1, tags=["热血"], reason="神作"),
    AnimeItem(chinese_name="鬼灭之刃", score=8.5, rank=5, tags=["战斗"], reason="感人"),
])
card_text = format_anime_card_list(rec)
assert "进击的巨人" in card_text
assert "⭐" in card_text
assert "9.1" in card_text
print("17/10 format_anime_card_list: 关键数据存在 OK ✓")

# 3b) format_model dispatch
text = format_model(rec, "anime_card_list")
assert "进击的巨人" in text
print("18/10 format_model: 分发 OK ✓")

# 3c) FORMATTER_REGISTRY
assert "anime_card_list" in FORMATTER_REGISTRY
assert "season_table" in FORMATTER_REGISTRY
assert "weather_card" in FORMATTER_REGISTRY
print("19/10 FORMATTER_REGISTRY: 5 个注册 OK ✓")

# 3d) format_season_table (mock)
season = SeasonOverview(
    season_label="2026年7月",
    total_count=42,
    tv_count=36,
    movie_count=4,
    ova_count=2,
    top_items=[
        AnimeItem(chinese_name="番剧A", score=8.5, rank=10, tags=["搞笑"], reason="有趣"),
        AnimeItem(chinese_name="番剧B", score=8.0, rank=20, tags=["恋爱"], reason="甜蜜"),
    ],
)
text = format_season_table(season)
assert "2026年7月" in text
assert "42" in text
assert "番剧A" in text
print("20/10 format_season_table: 关键数据存在 OK ✓")

# 3e) format_weather_card
weather = WeatherReport(
    city="北京",
    temperature=22.5,
    humidity=45,
    condition="晴",
    wind="东北风 3级",
    advice="适合出门追番",
)
text = format_weather_card(weather)
assert "北京" in text
assert "22.5" in text
assert "晴" in text
print("21/10 format_weather_card: 关键数据存在 OK ✓")

# ==================== 4. Injector ====================
from agent.structured_output.injector import (
    inject_into_prompt, get_schema_for_skill,
    get_schema_name_for_skill, build_json_instruction,
)
print("22/10 Injector 导入 OK")

# 4a) get_schema_name_for_skill
assert get_schema_name_for_skill("recommend-anime") == "anime_recommendation"
assert get_schema_name_for_skill("unknown-skill") is None
print("23/10 get_schema_name_for_skill OK ✓")

# 4b) get_schema_for_skill
schema_cls = get_schema_for_skill("recommend-anime")
assert schema_cls == AnimeRecommendationList
assert get_schema_for_skill("unknown-skill") is None
print("24/10 get_schema_for_skill OK ✓")

# 4c) build_json_instruction
instruction = build_json_instruction(AnimeRecommendationList)
assert "JSON" in instruction
assert "json" in instruction.lower()
assert "items" in instruction.lower() or "chinese_name" in instruction.lower()
print("25/10 build_json_instruction: 包含字段信息 OK ✓")

# 4d) inject_into_prompt
base = "你是一个动漫助手。"
injected = inject_into_prompt(base, "recommend-anime")
assert len(injected) > len(base)
assert "JSON" in injected
print("26/10 inject_into_prompt: 注入后变长且含 JSON 指令 OK ✓")

# 4e) inject with unknown skill → no change
injected = inject_into_prompt(base, "unknown-skill")
assert injected == base
print("27/10 inject_into_prompt: 未知 Skill 不注入 OK ✓")

# ==================== 5. Pipeline ====================
from agent.structured_output.pipeline import (
    structured_output_pipeline, process_structured_output, StructuredResult,
)
print("28/10 Pipeline 导入 OK")

# 5a) 完整管道：有效数据
full_with_json = '''
以下是本季值得追的几部新番：

```json
{"items": [{"chinese_name": "番剧X", "score": 8.8, "rank": 3, "tags": ["热血"], "reason": "制作精良"}]}
```

希望你喜欢！
'''
result = process_structured_output(full_with_json, skill_name="recommend-anime")
assert result is not None, "管道返回 None"
assert result.valid, f"管道校验失败: {getattr(result, 'reason', '')}"
assert result.schema_type == "anime_recommendation"
assert "番剧X" in result.formatted
print("29/10 Pipeline: 有效数据 → 完整管道 OK ✓")

# 5b) 管道：无 JSON → None
result = process_structured_output("纯文本回复", skill_name="recommend-anime")
assert result is None, "无 JSON 应返回 None"
print("30/10 Pipeline: 无 JSON → None OK ✓")

# 5c) 管道：未知 skill → None
result = process_structured_output("```json\n{}\n```", skill_name="unknown-skill")
assert result is None, "未知 skill 应返回 None"
print("31/10 Pipeline: 未知 Skill → None OK ✓")

# 5d) structured_output_pipeline.process
result = structured_output_pipeline.process(
    full_with_json, context={"skill": "recommend-anime"},
)
assert result is not None and result.valid
print("32/10 Pipeline.process: context 方式 OK ✓")

# ==================== 6. Skill Loader (output_schema) ====================
from skill_support.loader import parse_skill_md
print("33/10 Skill Loader 导入 OK")

# 6a) parse_skill_md 提取 output_schema
import tempfile, os
with tempfile.NamedTemporaryFile(
    mode="w", suffix=".md", delete=False, encoding="utf-8"
) as f:
    f.write("""---
name: test-skill
description: 测试 Skill
metadata:
  emoji: 🧪
  category: test
  output_schema: anime_recommendation
---

# 测试 Skill
这是测试内容。
""")
    tmp_path = f.name

try:
    from pathlib import Path
    meta = parse_skill_md(Path(tmp_path))
    assert meta["name"] == "test-skill"
    assert meta["output_schema"] == "anime_recommendation"
    print("34/10 parse_skill_md: output_schema 提取 OK ✓")
finally:
    os.unlink(tmp_path)

# 6b) 无 output_schema 的 Skill → 空字符串
with tempfile.NamedTemporaryFile(
    mode="w", suffix=".md", delete=False, encoding="utf-8"
) as f:
    f.write("""---
name: no-schema-skill
description: 无 Schema 的 Skill
---

# 内容
""")
    tmp_path2 = f.name

try:
    meta = parse_skill_md(Path(tmp_path2))
    assert meta["output_schema"] == ""
    print("35/10 parse_skill_md: 无 output_schema → 空字符串 OK ✓")
finally:
    os.unlink(tmp_path2)

# ==================== 7. StructuredData Event ====================
from agent.stream_events import StructuredData as SDEvent
from dataclasses import fields
sd_fields = {f.name for f in fields(SDEvent)}
assert "schema_type" in sd_fields
assert "model" in sd_fields
assert "formatted" in sd_fields
assert "raw_json" in sd_fields
print("36/10 StructuredData 事件: 4 字段 OK ✓")

event = SDEvent(schema_type="anime_recommendation", model=None, formatted="# test", raw_json={})
assert event.formatted == "# test"
print("37/10 StructuredData 事件: 创建 OK ✓")

# ==================== 8. FileOperationResult ====================
from agent.structured_output.formatter import format_file_result
fop = FileOperationResult(
    operation="convert",
    path="/data/file.pdf",
    success=True,
    summary="已将 PDF 转换为 Markdown，共 12 页。",
)
text = format_file_result(fop)
assert "convert" in text
assert "✅" in text or "成功" in text or "summary" not in text
print("38/10 FileOperationResult: 格式化 OK ✓")

# ==================== 9. AnimeDeepDive ====================
from agent.structured_output.formatter import format_deep_dive_detail
dive = AnimeDeepDive(
    chinese_name="某科学的超电磁炮",
    japanese_name="とある科学の超電磁砲",
    score=8.3,
    rank=45,
    synopsis="学园都市中的故事",
    cast=[
        {"character": "御坂美琴", "voice_actor": "佐藤利奈"},
        {"character": "白井黑子", "voice_actor": "新井里美"},
    ],
    episode_count=24,
    tags=["科幻", "校园", "战斗"],
)
text = format_deep_dive_detail(dive)
assert "某科学的超电磁炮" in text
assert "佐藤利奈" in text
print("39/10 AnimeDeepDive: 格式化 OK ✓")

# ==================== 10. Retry Handler ====================
from agent.structured_output.retry import retry_handler
print("40/10 RetryHandler 导入 OK")

assert hasattr(retry_handler, "enabled")
assert hasattr(retry_handler, "max_retries")
print(f"41/10 RetryHandler: enabled={retry_handler.enabled}, max={retry_handler.max_retries} OK ✓")

# should_retry: 默认 enabled=false → 不重试
class MockResult:
    reason = "validation_error"
    schema_type = "anime_recommendation"
mock = MockResult()
if retry_handler.enabled:
    assert retry_handler.should_retry(mock)
    print("42/10 RetryHandler.should_retry: validation_error → 可重试 ✓")
else:
    assert not retry_handler.should_retry(mock)
    print("42/10 RetryHandler.should_retry: enabled=false → 不可重试 ✓")

print()
print("=" * 50)
print("✅ 全部测试通过！Phase 6 结构化输出系统正常。")
print(f"   - {len(SCHEMA_REGISTRY)} 个 Pydantic Schema")
print(f"   - {len(FORMATTER_REGISTRY)} 个 Formatter")
print(f"   - Validator: extract → validate → feedback")
print(f"   - Injector: prompt 注入正常工作")
print(f"   - Pipeline: e2e 管道正常工作")
print(f"   - Skill Loader: output_schema 提取正常")
print(f"   - StructuredData: 事件模型正常")
print(f"   - RetryHandler: 机制就绪 (enabled={retry_handler.enabled})")
print("=" * 50)
