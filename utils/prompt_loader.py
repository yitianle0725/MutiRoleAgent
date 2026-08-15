"""
Prompt 加载器
=============
统一的系统提示词加载入口，支持新旧两种架构：

- **V2 (推荐)**: 通过 ``prompts/composer.py`` 动态组合
- **V1 (兼容)**: 直接读取 .txt 文件

外部代码只需调用此模块的函数，无需关心底层架构。
"""

from utils.config_handler import prompts_config
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


# ==================== V2: Composer 模式 ====================

def load_system_prompts(skills_summary: str = "") -> str:
    """加载系统提示词（V2 composer 优先，fallback V1 .txt）。

    优先使用 ``prompts/composer.py`` 动态组合 system/*.md，
    如果 composer 不可用或 system 文件缺失，回退到旧的 main_prompt.txt。

    Args:
        skills_summary: Skill 摘要文本（可选，由 react_agent 注入）。
    """
    try:
        from prompts.composer import compose_base_prompt
        result = compose_base_prompt(skills_summary=skills_summary)
        if result:
            logger.debug("[prompt_loader] 使用 V2 composer 加载系统提示词")
            return result
    except Exception as e:
        logger.warning(f"[prompt_loader] Composer 不可用，回退 V1: {e}")

    # V1 fallback: 直接读取 main_prompt.txt
    return _load_system_prompts_v1()


def _load_system_prompts_v1() -> str:
    """V1 fallback: 从 main_prompt.txt 读取系统提示词。"""
    try:
        system_prompt_path = get_abs_path(prompts_config["main_prompt_path"])
    except KeyError as e:
        logger.error(f"[prompt_loader] yaml 配置中缺少 main_prompt_path")
        raise e

    try:
        return open(system_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[prompt_loader] 读取系统提示词失败: {e}")
        raise e


# ==================== RAG / Report (保持原有逻辑) ====================

def load_rag_prompts():
    try:
        rag_summarize_prompt_path = get_abs_path(prompts_config["rag_summarize_prompt_path"])
    except KeyError as e:
        logger.error(f"[prompt_loader] yaml 配置中缺少 rag_summarize_prompt_path")
        raise e

    try:
        return open(rag_summarize_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[prompt_loader] 读取 RAG 提示词失败: {e}")
        raise e


def load_report_prompts():
    try:
        report_prompt_path = get_abs_path(prompts_config["report_prompt_path"])
    except KeyError as e:
        logger.error(f"[prompt_loader] yaml 配置中缺少 report_prompt_path")
        raise e

    try:
        return open(report_prompt_path, "r", encoding="utf-8").read()
    except Exception as e:
        logger.error(f"[prompt_loader] 读取 report 提示词失败: {e}")
        raise e


# ==================== 便捷函数 ====================

def compose_persona_prompt(
    persona_name: str,
    style: str = "default",
    skills_summary: str = "",
) -> str:
    """组装带角色人设的完整系统提示词。

    Args:
        persona_name: 角色名（如 "Cyrene"）。
        style: 语气风格（default / lively / healing / focused / sweet）。
        skills_summary: Skill 摘要文本。
    """
    try:
        from prompts.composer import compose_prompt
        return compose_prompt(
            persona=persona_name,
            style=style,
            skills_summary=skills_summary,
        )
    except Exception as e:
        logger.warning(f"[prompt_loader] Composer 不可用: {e}")
        # Fallback: 手动拼接 base prompt + persona overlay
        base = _load_system_prompts_v1()
        from utils.persona_loader import load_persona_overlay
        overlay = load_persona_overlay(persona_name)
        if overlay:
            base = (
                f"你现在正在扮演角色「{persona_name}」，"
                f"必须严格遵循以下人设进行对话：\n\n"
                f"{overlay}\n\n---\n\n## 工作指令\n\n{base}"
            )
        return base


if __name__ == '__main__':
    print(load_system_prompts()[:500])
    print("\n" + "=" * 60)
    print(load_report_prompts()[:500])
