"""
自动重试处理器
==============
校验失败的响应 → 直接 LLM 修正（不重入 ReAct 图）。

避免 ReAct 图重入的复杂性：
- 不需要重新发送工具 Schema（省 Token）
- 不需要重置图状态
- 不需要担心工具被重复调用

Phase 6b 组件，通过 ``config/structured_output.yaml`` 中的
``retry.enabled: true`` 启用。默认关闭。

使用方式::

    from agent.structured_output.retry import retry_handler
    if retry_handler.enabled:
        corrected = retry_handler.retry(original_text, failed_result, context)
"""

from __future__ import annotations

from utils.logger_handler import logger

# 配置加载
def _load_retry_cfg() -> dict:
    try:
        from utils.config_handler import get_abs_path
        import yaml
        path = get_abs_path("config/structured_output.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader).get("retry", {})
    except Exception:
        return {}

_RETRY_CFG = _load_retry_cfg()


class RetryHandler:
    """校验失败自动重试处理器。

    直接调用 LLM（不通过 Agent 图）要求修正 JSON 输出。
    避免 ReAct 图的 Tool Schema Token 开销和状态复杂性。
    """

    def __init__(self):
        self.enabled = _RETRY_CFG.get("enabled", False)
        self.max_retries = _RETRY_CFG.get("max_retries", 1)
        self.timeout = _RETRY_CFG.get("retry_timeout", 20)

    def should_retry(self, result) -> bool:
        """判断是否应该重试。

        可恢复的错误：JSON 结构错误、缺少必填字段、类型错误
        不可恢复的错误：响应中完全无 JSON（和 prompt 无关）、unknown_schema

        Args:
            result: ValidationResult 或 StructuredResult。

        Returns:
            是否应重试。
        """
        if not self.enabled:
            return False

        reason = getattr(result, "reason", "")
        # 只在 JSON 存在但校验失败时重试
        return reason in ("validation_error", "json_parse_error")

    def build_retry_prompt(
        self,
        original_text: str,
        result,
        context: dict | None = None,
    ) -> str:
        """构建修正提示词。

        Args:
            original_text: 原始 LLM 响应。
            result: 校验失败的 result。
            context: 上下文 dict。

        Returns:
            修正提示词文本。
        """
        from agent.structured_output.validator import build_error_feedback

        errors_text = build_error_feedback(result)
        schema_type = getattr(result, "schema_type", "")

        prompt = (
            f"你之前的回复中的 JSON 数据有格式错误。请根据以下反馈修正后，"
            f"重新输出**仅**修正后的 JSON 代码块。\n\n"
            f"## 错误反馈\n{errors_text}\n\n"
            f"## Schema 类型\n{schema_type}\n\n"
            f"请输出: ```json\n{{...}}\n```"
        )
        return prompt

    async def retry_async(
        self,
        original_text: str,
        result,
        context: dict | None = None,
    ) -> None:
        """异步重试：直接调用 LLM 修正 JSON。

        Args:
            original_text: 原始 LLM 响应。
            result: 校验失败的 ValidationResult / StructuredResult。
            context: 上下文 dict。

        Returns:
            修正后的 StructuredResult，或 None（重试失败）。
        """
        if not self.should_retry(result):
            return None

        skill_name = (context or {}).get("skill", "")
        retry_prompt = self.build_retry_prompt(original_text, result, context)

        try:
            from model.factory import chat_model
            from langchain_core.messages import HumanMessage

            logger.info(
                f"[RetryHandler] 开始修正: skill={skill_name}, "
                f"schema={getattr(result, 'schema_type', '')}"
            )

            response = await chat_model.ainvoke(
                [HumanMessage(content=retry_prompt)],
                # timeout not directly supported by all models;
                # wrapped in asyncio.wait_for at the caller level
            )

            content = response.content if hasattr(response, "content") else str(response)

            # 重新提取 + 校验
            from agent.structured_output.validator import extract_and_validate
            from agent.structured_output.injector import get_schema_name_for_skill, get_formatter_name_for_skill

            schema_name = get_schema_name_for_skill(skill_name)
            if not schema_name:
                return None

            validation = extract_and_validate(content, schema_name)

            if validation.valid:
                from agent.structured_output.formatter import format_model
                from agent.structured_output.pipeline import StructuredResult

                formatter_name = get_formatter_name_for_skill(skill_name)
                formatted = format_model(validation.model, formatter_name or "")

                logger.info(f"[RetryHandler] 修正成功: skill={skill_name}")
                return StructuredResult(
                    valid=True,
                    schema_type=schema_name,
                    model=validation.model,
                    formatted=formatted,
                    raw_json=validation.raw_json,
                )
            else:
                logger.warning(
                    f"[RetryHandler] 修正后仍校验失败: {validation.reason}"
                )
                return None

        except Exception as e:
            logger.warning(f"[RetryHandler] 重试异常: {e}")
            return None

    def retry(
        self,
        original_text: str,
        result,
        context: dict | None = None,
    ):
        """同步重试包装（内部调用异步版本）。

        在已有 event loop 的环境中使用线程池执行。
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            # 已有 event loop，使用 run_coroutine_threadsafe
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                self.retry_async(original_text, result, context),
                loop,
            )
            return future.result(timeout=self.timeout + 5)
        except RuntimeError:
            # 无 event loop，创建新的
            return asyncio.run(
                asyncio.wait_for(
                    self.retry_async(original_text, result, context),
                    timeout=self.timeout + 5,
                )
            )


# ==================== 模块级实例 ====================

retry_handler = RetryHandler()
