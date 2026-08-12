"""
结构化输出包
============
Phase 6: 从自由文本升级为 Schema 驱动的结构化输出。

核心组件
--------
- ``schemas.py``: Pydantic 输出模型定义 + Schema 注册表
- ``validator.py``: JSON 提取 + Pydantic 校验 + 错误反馈
- ``formatter.py``: 领域格式化器（Markdown 卡片/表格）
- ``injector.py``: Prompt 注入器（追加 JSON 格式指令）
- ``pipeline.py``: 管道编排器（串联 Inject → Validate → Format）
- ``retry.py``: 自动重试处理器（校验失败时直接 LLM 修正）

使用方式
--------
快速处理::

    from agent.structured_output import process_structured_output
    result = process_structured_output(response_text, skill_name="recommend-anime")

完整管道::

    from agent.structured_output import structured_output_pipeline
    result = structured_output_pipeline.process(
        full_response,
        context={"skill": "recommend-anime"},
    )

Prompt 注入::

    from agent.structured_output import inject_into_prompt
    prompt = inject_into_prompt(base_prompt, skill_name="recommend-anime")
"""

from agent.structured_output.schemas import (
    AnimeItem,
    AnimeRecommendationList,
    SeasonOverview,
    AnimeDeepDive,
    WeatherReport,
    FileOperationResult,
    SCHEMA_REGISTRY,
)
from agent.structured_output.validator import (
    ValidationResult,
    extract_json,
    validate_output,
    build_error_feedback,
    extract_and_validate,
)
from agent.structured_output.formatter import (
    FORMATTER_REGISTRY,
    format_model,
    format_anime_card_list,
    format_season_table,
    format_deep_dive_detail,
    format_weather_card,
    format_file_result,
)
from agent.structured_output.injector import (
    get_schema_for_skill,
    get_schema_name_for_skill,
    get_formatter_name_for_skill,
    build_json_instruction,
    inject_into_prompt,
)
from agent.structured_output.pipeline import (
    StructuredOutputPipeline,
    StructuredResult,
    structured_output_pipeline,
    process_structured_output,
)
from agent.structured_output.retry import (
    RetryHandler,
    retry_handler,
)

__all__ = [
    # Schemas
    "AnimeItem",
    "AnimeRecommendationList",
    "SeasonOverview",
    "AnimeDeepDive",
    "WeatherReport",
    "FileOperationResult",
    "SCHEMA_REGISTRY",
    # Validator
    "ValidationResult",
    "extract_json",
    "validate_output",
    "build_error_feedback",
    "extract_and_validate",
    # Formatter
    "FORMATTER_REGISTRY",
    "format_model",
    "format_anime_card_list",
    "format_season_table",
    "format_deep_dive_detail",
    "format_weather_card",
    "format_file_result",
    # Injector
    "get_schema_for_skill",
    "get_schema_name_for_skill",
    "get_formatter_name_for_skill",
    "build_json_instruction",
    "inject_into_prompt",
    # Pipeline
    "StructuredOutputPipeline",
    "StructuredResult",
    "structured_output_pipeline",
    "process_structured_output",
    # Retry
    "RetryHandler",
    "retry_handler",
]
