"""Roleplay 表达层。

该模块只负责把事实转换成用户可读文本，不联网、不调用工具，也不改变事实状态。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.results import AgentFactResult


ROLEPLAY_SYSTEM_PROMPT = """你是一个轻量角色表达层。
只能使用系统或用户明确提供的事实，不得联网、调用工具、检查文件或查询记忆。
不得声称已经搜索、检查、修复、完成或验证事实中没有出现的事情。
必须保留路径、URL、时间、错误、警告、JSON 和不确定性。
失败、取消、等待输入必须如实表达，不能改写成成功。"""

try:
    import os
    from prompts import prompt_registry
    _PROMPT_VERSION = os.getenv("PROMPT_ROLEPLAY_VERSION", "v1")
    _ROLEPLAY_TEMPLATE = prompt_registry.get("roleplay", _PROMPT_VERSION)
    if _ROLEPLAY_TEMPLATE.strip():
        ROLEPLAY_SYSTEM_PROMPT += f"\n\nPrompt 版本：{_PROMPT_VERSION}\n{_ROLEPLAY_TEMPLATE}"
except (OSError, ValueError, ImportError):
    _PROMPT_VERSION = "inline"

ModelFactory = Callable[[str | None], Any]


class RoleplayEngine:
    """隔离聊天、ACK（确认）和 Agent 结果表达。"""

    def __init__(
        self,
        model: Any | None = None,
        *,
        model_factory: ModelFactory | None = None,
        ack_model: Any | None = None,
        ack_model_factory: ModelFactory | None = None,
        max_tokens: int | None = None,
        ack_max_tokens: int | None = None,
    ) -> None:
        self._model = model
        self._model_factory = model_factory
        self._ack_model = ack_model
        self._ack_model_factory = ack_model_factory
        import os
        self._max_tokens = max(int(max_tokens or os.getenv("ROLEPLAY_MAX_TOKENS", "1024")), 1)
        self._ack_max_tokens = max(int(ack_max_tokens or os.getenv("ACK_MAX_TOKENS", "128")), 1)

    def _resolve_model(self, persona: str | None = None) -> Any:
        if self._model_factory:
            return self._model_factory(persona)
        if self._model is not None:
            return self._model
        from model.factory import roleplay_model
        return roleplay_model

    def _resolve_ack_model(self, persona: str | None = None) -> Any:
        if self._ack_model_factory:
            return self._ack_model_factory(persona)
        if self._ack_model is not None:
            return self._ack_model
        from model.factory import ack_model
        return ack_model

    async def _generate(
        self,
        instruction: str,
        *,
        persona: str | None = None,
        history: Sequence[Any] = (),
        model: Any | None = None,
        max_tokens: int | None = None,
    ) -> str:
        selected = model or self._resolve_model(persona)
        system = ROLEPLAY_SYSTEM_PROMPT
        if persona:
            system += f"\n当前角色名：{persona}。保持角色语气，但不要改变事实。"
        messages = [SystemMessage(content=system), *history, HumanMessage(content=instruction)]
        try:
            bound = selected
            if hasattr(selected, "bind"):
                try:
                    bound = selected.bind(max_tokens=max_tokens or self._max_tokens)
                except Exception:
                    bound = selected
            response = await bound.ainvoke(messages)
        except TypeError:
            response = await selected.ainvoke(messages)
        content = getattr(response, "content", response)
        return str(content or "").strip()

    async def chat_reply(self, user_input: str, *, persona: str | None = None, history: Sequence[Any] = ()) -> str:
        try:
            result = await self._generate(f"直接回复用户，保持简洁自然。\n用户：{user_input}", persona=persona, history=history)
        except Exception:
            result = ""
        return result or user_input

    async def delegated_ack(self, user_input: str, *, persona: str | None = None) -> str:
        try:
            result = await self._generate(
                f"任务即将交给后台 Agent 处理。只回复一句简短确认，不要声称任务已完成。\n用户：{user_input}",
                persona=persona,
                model=self._resolve_ack_model(persona),
                max_tokens=self._ack_max_tokens,
            )
        except Exception:
            result = ""
        return result or "我先帮你处理一下，完成后把结果告诉你。"

    async def stream_chat_reply(self, user_input: str, *, persona: str | None = None, history: Sequence[Any] = ()) -> AsyncIterator[str]:
        model = self._resolve_model(persona)
        messages = [SystemMessage(content=ROLEPLAY_SYSTEM_PROMPT), *history, HumanMessage(content=user_input)]
        if not hasattr(model, "astream"):
            yield await self.chat_reply(user_input, persona=persona, history=history)
            return
        try:
            bound = model.bind(max_tokens=self._max_tokens) if hasattr(model, "bind") else model
            async for chunk in bound.astream(messages):
                content = getattr(chunk, "content", chunk)
                if content:
                    yield str(content)
        except Exception:
            yield user_input

    async def present_agent_result(self, fact: AgentFactResult, *, user_input: str = "", persona: str | None = None) -> str:
        if fact.status != "completed" or fact.errors:
            return self._fallback_fact(fact)
        fact_text = fact.text.strip()
        if not fact_text:
            return self._fallback_fact(fact)
        instruction = (
            "请把下面 Agent 已产生的事实结果交给用户，只做少量角色化润色。"
            "不得增加事实、删除错误或改变成功/失败状态。\n"
            f"用户问题：{user_input}\n执行状态：{fact.status}\nAgent 事实：\n{fact_text}"
        )
        try:
            result = await self._generate(instruction, persona=persona)
        except Exception:
            result = ""
        return result or self._fallback_fact(fact)

    async def present_agent_failure(self, error_text: str, *, user_input: str = "", persona: str | None = None) -> str:
        return await self.present_agent_result(AgentFactResult(status="failed", text=error_text, errors=[error_text]), user_input=user_input, persona=persona)

    async def present_agent_cancelled(self, detail: str = "", *, persona: str | None = None) -> str:
        return await self.present_agent_result(AgentFactResult(status="cancelled", text=detail), persona=persona)

    async def present_user_input_request(self, question: str, *, persona: str | None = None) -> str:
        try:
            result = await self._generate(f"请生成一句角色化引导语，然后原样保留这个问题：{question}", persona=persona)
        except Exception:
            result = ""
        return f"{result}\n{question}".strip() if result else question

    async def present_waiting_for_input(self, question: str, *, persona: str | None = None) -> str:
        return await self.present_user_input_request(question, persona=persona)

    @staticmethod
    def _fallback_fact(fact: AgentFactResult) -> str:
        if fact.status == "failed":
            detail = "; ".join(fact.errors) or fact.text or "未知错误"
            return f"处理失败：{detail}"
        if fact.status == "cancelled":
            return f"处理已取消。{fact.text}".strip()
        if fact.status == "waiting_for_input":
            return fact.text or "还需要你补充一些信息。"
        return fact.text or "没有可展示的结果。"
