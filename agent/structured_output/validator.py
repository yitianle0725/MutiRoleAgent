"""
JSON 提取 + Pydantic 校验
=========================
从 LLM 自由文本响应中提取 JSON 代码块，并对指定 Schema 进行 Pydantic 校验。

提取策略（按优先级）:
1. ```json ... ``` 或 ``` ... ``` 围栏代码块
2. 裸 { ... } JSON 对象（括号匹配）
3. 裸 [ ... ] JSON 数组（括号匹配）

校验失败时生成中文错误反馈，供自动重试使用。

使用方式::

    from agent.structured_output.validator import (
        ValidationResult, extract_json, validate_output, build_error_feedback,
    )
    data = extract_json(llm_response)
    if data:
        result = validate_output(data, AnimeRecommendationList)
        if result.valid:
            print(result.model)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from utils.logger_handler import logger


# ==================== 数据结构 ====================

@dataclass
class ValidationResult:
    """校验结果。"""
    valid: bool = False
    schema_type: str = ""
    model: BaseModel | None = None
    raw_json: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    reason: str = ""  # "ok" | "no_json_found" | "validation_error" | "json_parse_error"


@dataclass(frozen=True, slots=True)
class JsonExtraction:
    """解析后的 JSON，以及它在原始回答中的准确位置。"""

    data: dict
    start: int
    end: int


# ==================== JSON 提取 ====================

def extract_json_with_span(text: str) -> JsonExtraction | None:
    """提取 JSON，并保留源区间，供最终正文安全移除。"""

    if not text:
        return None

    fenced_patterns = [
        re.compile(r'```json\s*\n(.*?)\n```', re.DOTALL),
        re.compile(r'```\s*\n(\{.*?\})\s*\n```', re.DOTALL),
        re.compile(r'```\s*\n(\[.*?\])\s*\n```', re.DOTALL),
    ]
    for pattern in fenced_patterns:
        match = pattern.search(text)
        if not match:
            continue
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        data = {"items": parsed} if isinstance(parsed, list) else parsed
        if isinstance(data, dict):
            return JsonExtraction(data=data, start=match.start(), end=match.end())

    for opening, closing in (("{", "}"), ("[", "]")):
        try:
            start = text.index(opening)
        except ValueError:
            continue
        depth = 0
        for index in range(start, len(text)):
            if text[index] == opening:
                depth += 1
            elif text[index] == closing:
                depth -= 1
                if depth != 0:
                    continue
                end = index + 1
                try:
                    parsed = json.loads(text[start:end])
                except json.JSONDecodeError:
                    break
                data = {"items": parsed} if isinstance(parsed, list) else parsed
                if isinstance(data, dict):
                    return JsonExtraction(data=data, start=start, end=end)
                break
    return None


def extract_json(text: str) -> dict | None:
    """从文本中提取 JSON 对象。

    依次尝试三种策略，返回第一个成功解析的 dict。
    如果文本无 JSON，返回 None。

    Args:
        text: LLM 响应文本（可能包含 JSON 代码块）。

    Returns:
        解析成功的 dict，或 None。
    """
    extraction = extract_json_with_span(text)
    return extraction.data if extraction else None


def remove_extracted_json(text: str) -> str:
    """只移除能够成功解析的 JSON 区间，保留其余自然语言。"""

    extraction = extract_json_with_span(text)
    if extraction is None:
        return text.strip()
    remaining = text[:extraction.start] + text[extraction.end:]
    return remaining.strip()


# ==================== Schema 校验 ====================

def validate_output(
    data: dict,
    schema: type[BaseModel],
    schema_type: str = "",
) -> ValidationResult:
    """对提取的数据执行 Pydantic 校验。

    Args:
        data: 从 LLM 响应中提取的 JSON dict。
        schema: 目标 Pydantic 模型类。
        schema_type: Schema 名称（如 "anime_recommendation"）。

    Returns:
        ValidationResult。
    """
    if not data:
        return ValidationResult(
            valid=False,
            schema_type=schema_type,
            reason="no_json_found",
        )

    try:
        model = schema.model_validate(data)
        return ValidationResult(
            valid=True,
            schema_type=schema_type,
            model=model,
            raw_json=data,
            reason="ok",
        )
    except ValidationError as e:
        errors_list = []
        for err in e.errors():
            errors_list.append({
                "loc": list(err["loc"]),
                "type": err["type"],
                "msg": err["msg"],
            })
        logger.debug(
            f"[StructuredOutput] 校验失败: schema={schema_type}, "
            f"errors={len(errors_list)}"
        )
        return ValidationResult(
            valid=False,
            schema_type=schema_type,
            raw_json=data,
            errors=errors_list,
            reason="validation_error",
        )
    except Exception as e:
        logger.warning(f"[StructuredOutput] 校验异常: {e}")
        return ValidationResult(
            valid=False,
            schema_type=schema_type,
            raw_json=data,
            errors=[{"loc": [], "type": "exception", "msg": str(e)}],
            reason="json_parse_error",
        )


# ==================== 错误反馈 ====================

def build_error_feedback(result: ValidationResult) -> str:
    """将 Pydantic 校验错误映射为中文反馈，供模型自修正。

    Args:
        result: 校验失败的 ValidationResult。

    Returns:
        中文错误描述文本。
    """
    if not result.errors:
        return "JSON 格式错误，请检查语法。"

    messages = []
    for err in result.errors:
        loc = " → ".join(str(l) for l in err["loc"]) if err["loc"] else "根对象"
        err_type = err["type"]
        msg = err.get("msg", "")

        if err_type == "missing":
            messages.append(f"缺少必填字段: {loc}")
        elif err_type in ("string_type", "int_type", "float_type",
                          "list_type", "dict_type", "bool_type"):
            messages.append(f"字段 '{loc}' 类型不正确 — {msg}")
        elif err_type in ("less_than", "less_than_equal",
                          "greater_than", "greater_than_equal"):
            messages.append(f"字段 '{loc}' 数值超出允许范围 — {msg}")
        elif err_type == "too_short" or err_type == "too_long":
            messages.append(f"字段 '{loc}' 长度不符合要求 — {msg}")
        elif err_type == "value_error":
            messages.append(f"字段 '{loc}' 值无效 — {msg}")
        else:
            messages.append(f"字段 '{loc}': {msg}")

    return "\n".join(messages)


# ==================== 便捷函数 ====================

def extract_and_validate(
    text: str,
    schema_name: str,
    schema_registry: dict[str, type[BaseModel]] | None = None,
) -> ValidationResult:
    """一步完成提取 + 校验。

    Args:
        text: LLM 响应文本。
        schema_name: Schema 注册表键名。
        schema_registry: Schema 注册表（默认使用内置 SCHEMA_REGISTRY）。

    Returns:
        ValidationResult。
    """
    if schema_registry is None:
        from agent.structured_output.schemas import SCHEMA_REGISTRY
        schema_registry = SCHEMA_REGISTRY

    schema_cls = schema_registry.get(schema_name)
    if schema_cls is None:
        return ValidationResult(
            valid=False,
            schema_type=schema_name,
            reason="unknown_schema",
            errors=[{"loc": [], "type": "unknown_schema",
                     "msg": f"Unknown schema: {schema_name}"}],
        )

    data = extract_json(text)
    return validate_output(data, schema_cls, schema_type=schema_name)
