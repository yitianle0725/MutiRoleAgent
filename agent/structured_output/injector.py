"""
Prompt 注入器
=============
根据当前激活的 Skill，向 System Prompt 追加 JSON 结构化输出指令。

注入的指令要求模型在自然语言回复中嵌入 `` ```json ... ``` `` 围栏代码块，
包含符合指定 Pydantic Schema 的 JSON 数据。

使用方式::

    from agent.structured_output.injector import inject_into_prompt
    prompt = inject_into_prompt(base_prompt, skill_name="recommend-anime")
"""

from __future__ import annotations

from pydantic import BaseModel

from utils.logger_handler import logger

# 配置加载
def _load_structured_output_cfg() -> dict:
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/structured_output.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    except Exception:
        return {}

_CFG = _load_structured_output_cfg()
_SCHEMA_CFG = _CFG.get("schemas", {})


# ==================== Schema 查找 ====================

def get_schema_name_for_skill(skill_name: str) -> str | None:
    """根据 Skill 名称查找对应的 Schema 键名。

    Args:
        skill_name: Skill 名称（如 "recommend-anime"）。

    Returns:
        Schema 键名（如 "anime_recommendation"），或 None。
    """
    cfg = _SCHEMA_CFG.get(skill_name, {})
    return cfg.get("schema") if cfg else None


def get_formatter_name_for_skill(skill_name: str) -> str | None:
    """根据 Skill 名称查找对应的 Formatter 键名。"""
    cfg = _SCHEMA_CFG.get(skill_name, {})
    return cfg.get("formatter") if cfg else None


def get_schema_for_skill(skill_name: str) -> type[BaseModel] | None:
    """根据 Skill 名称查找对应的 Pydantic Schema 类。

    Args:
        skill_name: Skill 名称。

    Returns:
        Pydantic 模型类，或 None。
    """
    schema_name = get_schema_name_for_skill(skill_name)
    if not schema_name:
        return None

    from agent.structured_output.schemas import SCHEMA_REGISTRY
    return SCHEMA_REGISTRY.get(schema_name)


# ==================== 指令生成 ====================

def build_json_instruction(schema_cls: type[BaseModel]) -> str:
    """根据 Pydantic Schema 生成 JSON 格式指令文本。

    从 Schema 的 Field description 和类型注解中提取字段信息，
    生成简洁的 JSON 示例和约束说明。

    Args:
        schema_cls: Pydantic 模型类。

    Returns:
        Markdown 格式的指令文本。
    """
    import inspect

    lines = [
        "\n\n---\n\n",
        "## 📋 结构化输出要求",
        "",
        "请在回复的**末尾**，用 ```json 代码块输出以下 JSON 格式的数据：",
        "",
    ]

    # 生成每个字段的说明
    fields = schema_cls.model_fields
    for field_name, field_info in fields.items():
        desc = field_info.description or ""
        default = field_info.default
        annotation = field_info.annotation

        # 类型名
        type_name = _type_str(annotation)

        if field_info.is_required():
            lines.append(f"- **`{field_name}`** ({type_name}，**必填**): {desc}")
        else:
            if default is not None and default != "" and default != []:
                lines.append(f"- **`{field_name}`** ({type_name}，可选，默认 `{default}`): {desc}")
            else:
                lines.append(f"- **`{field_name}`** ({type_name}，可选): {desc}")

    # 生成 JSON 示例
    example = _build_example(schema_cls)
    lines.append(f"\n### 示例格式\n```json\n{example}\n```")
    lines.append("\n**注意**：只输出一个 JSON 代码块，包含实际数据而非示例值。")

    return "\n".join(lines)


def _type_str(annotation) -> str:
    """类型注解 → 可读字符串。"""
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return "数组"
    if origin is dict:
        return "对象"
    type_name = str(annotation)
    # 简化
    type_name = type_name.replace("<class '", "").replace("'>", "")
    type_name = type_name.replace("NoneType", "null")
    if "|" in type_name:
        type_name = type_name.split("|")[0].strip()
    return type_name


def _build_example(schema_cls: type[BaseModel]) -> str:
    """为 Schema 生成简单的示例 JSON。"""
    import json

    example = {}
    for field_name, field_info in schema_cls.model_fields.items():
        annotation = field_info.annotation
        origin = getattr(annotation, "__origin__", None)

        if origin is list:
            example[field_name] = []
        elif origin is dict:
            example[field_name] = {}
        elif field_name == "type":
            example[field_name] = field_info.default if field_info.default else "string"
        elif annotation in (int, float) or (hasattr(annotation, "__args__") and
              any(a in (int, float) for a in (annotation.__args__ if hasattr(annotation, "__args__") else []))):
            example[field_name] = 0
        elif annotation is bool:
            example[field_name] = True
        else:
            example[field_name] = "…" if field_info.is_required() else ""

    return json.dumps(example, ensure_ascii=False, indent=2)


# ==================== 注入 ====================

def inject_into_prompt(prompt: str, skill_name: str = "") -> str:
    """向已有 Prompt 追加结构化输出指令。

    如果 Skill 没有注册 output_schema，原样返回。

    Args:
        prompt: 当前 System Prompt。
        skill_name: 当前激活的 Skill 名称。

    Returns:
        追加了 JSON 指令的 Prompt。
    """
    schema_cls = get_schema_for_skill(skill_name)
    if schema_cls is None:
        logger.debug(f"[StructuredOutput] Skill '{skill_name}' 无 output_schema，跳过注入")
        return prompt

    instruction = build_json_instruction(schema_cls)
    logger.info(
        f"[StructuredOutput] 注入 JSON 指令: skill={skill_name}, "
        f"schema={get_schema_name_for_skill(skill_name)}, "
        f"len={len(instruction)}"
    )
    return prompt + instruction
