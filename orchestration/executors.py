"""显式 Chat / Work 执行器。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage

from agent.harness_events import HarnessEvent
from memory.context_trimmer import trim_history
from model.factory import chat_model
from orchestration.models import TurnContext
from orchestration.session_runner import SessionAgentRunner


StreamEvent = HarnessEvent


class ConversationExecutor(Protocol):
    async def stream(self, prompt: str, context: TurnContext) -> AsyncIterator[StreamEvent]: ...


class ChatExecutor:
    """无工具、完整 Persona Prompt 的轻量聊天执行器。"""

    def __init__(self, model=chat_model) -> None:
        self._model = model

    async def stream(self, prompt: str, context: TurnContext) -> AsyncIterator[StreamEvent]:
        system_prompt = context.prompt_layers.render() if context.prompt_layers else ""
        history = trim_history(context.history)
        messages = [SystemMessage(content=system_prompt), *history, HumanMessage(content=prompt)]
        async for chunk in self._model.astream(messages):
            content = getattr(chunk, "content", chunk)
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) if isinstance(item, dict) else str(item)
                    for item in content
                )
            if content:
                yield HarnessEvent.final_text(str(content), delta=True)


class WorkExecutor:
    """复用现有 LangGraph Agent，但不再参与模式判断。"""

    def __init__(self, runner: SessionAgentRunner) -> None:
        self._runner = runner

    async def stream(self, prompt: str, context: TurnContext) -> AsyncIterator[StreamEvent]:
        if context.prompt_layers:
            runtime_context = "\n\n---\n\n".join(
                part for part in (
                    context.prompt_layers.mode_context,
                    context.prompt_layers.user_context,
                    context.prompt_layers.session_context,
                ) if part
            )
        else:
            runtime_context = ""
        async for event in self._runner.stream(
            context.session.session_id,
            prompt,
            user_id=context.session.user_id,
            persona=context.session.persona_name,
            runtime_context=runtime_context,
        ):
            yield event
