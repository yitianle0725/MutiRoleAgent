"""
结构化输出管道
==============
将 Inject → Validate → Format 串联为统一管道，
在 LLM 响应完成后调用。

管道流程::

    full_response (str)
        │
        ▼
    extract_json() ──→ 提取 JSON 代码块
        │
        ▼
    validate_output() ──→ Pydantic 校验
        │
        ▼
    format_model() ──→ 生成格式化 Markdown
        │
        ▼
    StructuredResult

使用方式::

    from agent.structured_output.pipeline import structured_output_pipeline

    result = structured_output_pipeline.process(
        full_response,
        context={"skill": "recommend-anime"},
    )
    if result and result.valid:
        yield HarnessEvent.structured_data(
            schema_type=result.schema_type,
            data=result.raw_json,
        )
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from utils.logger_handler import logger


# ==================== 数据结构 ====================

@dataclass
class StructuredResult:
    """管道处理结果。"""
    valid: bool = False
    schema_type: str = ""
    model: BaseModel | None = None
    formatted: str = ""
    raw_json: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    reason: str = ""


# ==================== 管道 ====================

class StructuredOutputPipeline:
    """结构化输出管道。

    整合 JSON 提取、Schema 校验和 Markdown 格式化。
    单例模式，通过 ``structured_output_pipeline`` 模块级实例访问。

    使用示例::

        pipeline = StructuredOutputPipeline()
        result = pipeline.process(
            response_text,
            context={"skill": "recommend-anime"},
        )
    """

    def process(
        self,
        full_response: str,
        context: dict | None = None,
    ) -> StructuredResult | None:
        """处理 LLM 完整响应，尝试提取和校验结构化数据。

        Args:
            full_response: LLM 的完整文本响应。
            context: 上下文 dict，需包含 ``skill`` 键（Skill 名称）。

        Returns:
            StructuredResult（valid=True 表示校验通过），
            或者 None（Skill 无 output_schema / 无 JSON 可提取）。
        """
        context = context or {}
        skill_name = context.get("skill", "")

        if not skill_name:
            return None

        # 1) 查找 Schema 和 Formatter
        from agent.structured_output.injector import (
            get_schema_name_for_skill,
            get_formatter_name_for_skill,
        )
        schema_name = get_schema_name_for_skill(skill_name)
        formatter_name = get_formatter_name_for_skill(skill_name)

        if not schema_name:
            logger.debug(f"[Pipeline] Skill '{skill_name}' 无 output_schema")
            return None

        # 2) 提取 JSON
        from agent.structured_output.validator import (
            extract_json, validate_output,
        )
        data = extract_json(full_response)
        if data is None:
            logger.debug(
                f"[Pipeline] 未找到 JSON: skill={skill_name}, "
                f"response_len={len(full_response)}"
            )
            return None

        # 3) 校验
        from agent.structured_output.schemas import SCHEMA_REGISTRY
        schema_cls = SCHEMA_REGISTRY.get(schema_name)
        if schema_cls is None:
            logger.warning(f"[Pipeline] 未知 Schema: {schema_name}")
            return None

        validation = validate_output(data, schema_cls, schema_type=schema_name)

        if not validation.valid:
            logger.info(
                f"[Pipeline] 校验失败: skill={skill_name}, "
                f"schema={schema_name}, reason={validation.reason}, "
                f"errors={len(validation.errors)}"
            )
            return StructuredResult(
                valid=False,
                schema_type=schema_name,
                raw_json=data,
                errors=validation.errors,
                reason=validation.reason,
            )

        # 4) 格式化
        from agent.structured_output.formatter import format_model
        formatted = format_model(validation.model, formatter_name or "")

        logger.info(
            f"[Pipeline] 结构化输出成功: skill={skill_name}, "
            f"schema={schema_name}, formatted_len={len(formatted)}"
        )

        return StructuredResult(
            valid=True,
            schema_type=schema_name,
            model=validation.model,
            formatted=formatted,
            raw_json=data,
            reason="ok",
        )

    def process_with_retry(
        self,
        full_response: str,
        context: dict | None = None,
        max_retries: int = 1,
    ) -> StructuredResult | None:
        """处理 LLM 响应，失败时自动重试。

        Args:
            full_response: LLM 的完整文本响应。
            context: 上下文 dict。
            max_retries: 最大重试次数。

        Returns:
            StructuredResult 或 None。
        """
        result = self.process(full_response, context)
        if result and result.valid:
            return result

        # 重试逻辑
        retry_cfg = {}
        try:
            from agent.structured_output.retry import retry_handler
            if retry_handler.enabled and result:
                for attempt in range(max_retries):
                    logger.info(
                        f"[Pipeline] 重试 {attempt + 1}/{max_retries}: "
                        f"reason={result.reason}"
                    )
                    retry_result = retry_handler.retry(
                        full_response, result, context
                    )
                    if retry_result and retry_result.valid:
                        return retry_result
        except Exception as e:
            logger.warning(f"[Pipeline] 重试异常: {e}")

        return result  # 返回原始失败结果


# ==================== 模块级实例 ====================

structured_output_pipeline = StructuredOutputPipeline()


# ==================== 便捷函数 ====================

def process_structured_output(
    full_response: str,
    skill_name: str = "",
) -> StructuredResult | None:
    """快速处理结构化输出的便捷函数。"""
    return structured_output_pipeline.process(
        full_response,
        context={"skill": skill_name},
    )
