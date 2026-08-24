"""独立角色表达层。

角色层只接收用户文本或 Agent 已产生的事实，不拥有工具注册表，也不执行
联网、文件和知识库操作。模型不可用时直接返回原始事实，避免二次幻觉。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent.results import AgentFactResult


ROLEPLAY_SYSTEM_PROMPT = """你是一个轻量角色表达层。

你只能使用系统或用户明确提供的事实，不得自行联网、调用工具、检查文件或查询记忆。
不得声称已经搜索、检查、修复、完成或验证任何没有出现在事实中的事情。
对 Agent 结果只做少量语气包装，必须保留路径、URL、时间、错误、警告、JSON 和不确定性。
如果事实失败或不完整，必须如实表达，不能把失败改写为成功。"""


ModelFactory = Callable[[str | None], Any]


class RoleplayEngine:
    """负责聊天、ACK 和事实结果表达，不负责 Agent 执行。"""

    def __init__(
        self,
        model: Any | None = None,
        *,
        model_factory: ModelFactory | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._model = model
        self._model_factory = model_factory
        self._max_tokens = max(int(max_tokens), 1)

    def _resolve_model(self, persona: str | None = None) -> Any:
        if self._model_factory is not None:
            return self._model_factory(persona)
        if self._model is not None:
            return self._model
        from model.factory import chat_model

        return chat_model

    async def _generate(
        self,
        instruction: str,
        *,
        persona: str | None = None,
        history: Sequence[Any] = (),
    ) -> str:
        model = self._resolve_model(persona)
        system = ROLEPLAY_SYSTEM_PROMPT
        if persona:
            system += f"\n当前角色名：{persona}。保持该角色的语气，但不要改变事实。"
        messages = [SystemMessage(content=system), *history, HumanMessage(content=instruction)]
        try:
            response = await model.ainvoke(
                messages,
                config={"configurable": {"max_tokens": self._max_tokens}},
            )
        except TypeError:
            response = await model.ainvoke(messages)
        content = getattr(response, "content", response)
        return str(content or "").strip()

    async def chat_reply(
        self,
        user_input: str,
        *,
        persona: str | None = None,
        history: Sequence[Any] = (),
    ) -> str:
        result = await self._generate(
            f"请直接回复用户，保持简洁自然。\n用户：{user_input}",
            persona=persona,
            history=history,
        )
        return result or user_input

    async def delegated_ack(self, user_input: str, *, persona: str | None = None) -> str:
        result = await self._generate(
            f"任务即将交给后台 Agent 处理。只回复一句简短确认，不要声称任务已完成。\n用户：{user_input}",
            persona=persona,
        )
        return result or "我先帮你处理一下，完成后把结果告诉你。"

    async def present_agent_result(
        self,
        fact: AgentFactResult,
        *,
        user_input: str = "",
        persona: str | None = None,
    ) -> str:
        fact_text = fact.text.strip()
        if not fact_text:
            return self._fallback_fact(fact)
        instruction = (
            "请把下面 Agent 已产生的事实结果交给用户。只做少量角色化润色，"
            "不得增加事实、删除错误或改变成功/失败状态。\n"
            f"用户问题：{user_input}\n"
            f"执行状态：{fact.status}\n"
            f"Agent 事实：\n{fact_text}"
        )
        try:
            result = await self._generate(instruction, persona=persona)
        except Exception:
            result = ""
        return result or self._fallback_fact(fact)

    async def present_user_input_request(
        self,
        question: str,
        *,
        persona: str | None = None,
    ) -> str:
        try:
            result = await self._generate(
                f"Agent 需要用户补充信息。请只生成一句角色化引导语，随后原样保留问题：{question}",
                persona=persona,
            )
        except Exception:
            result = ""
        return f"{result}\n{question}".strip() if result else question

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
