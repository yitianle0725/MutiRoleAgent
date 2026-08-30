"""按 Session 绑定构建一轮对话所需的分层上下文。"""

from __future__ import annotations

import asyncio
import json

from memory.chat_db import ChatDB
from memory.user_profile_extractor import build_profile_context
from orchestration.models import PromptLayers, SessionContext, TurnContext
from prompts.composer import compose_prompt


CHAT_MODE_PROMPT = """## 当前模式：Chat
专注长期角色陪伴和自然交流。不得调用工具，不得声称已经搜索、读取文件或执行外部操作。"""

WORK_MODE_PROMPT = """## 当前模式：Work
你可以使用已提供的工具完成检索、分析和任务执行。
优先级始终是：任务正确性 > 信息完整性 > 角色表达。
角色风格只能影响自然语言表达，不得改写工具名、参数、路径、代码、JSON、错误或事实结果。"""


class SessionContextBuilder:
    def __init__(self, database: ChatDB) -> None:
        self._database = database

    async def require_session(self, session_id: str) -> SessionContext:
        return await asyncio.to_thread(self._database.require_session, session_id)

    async def build(self, session: SessionContext, prompt: str) -> TurnContext:
        history, memories, persona_profile, global_profile = await asyncio.gather(
            asyncio.to_thread(self._database.get_history, session.session_id),
            asyncio.to_thread(self._database.list_scoped_memories, session),
            asyncio.to_thread(
                self._database.get_user_persona_profile,
                session.user_id,
                session.persona_id,
            ),
            asyncio.to_thread(build_profile_context, session.user_id),
        )

        persona_context = await asyncio.to_thread(
            compose_prompt,
            persona=session.persona_name,
        )
        mode_context = CHAT_MODE_PROMPT if session.mode == "chat" else WORK_MODE_PROMPT
        user_context = self._build_user_context(global_profile, persona_profile, memories)
        session_context = self._build_session_context(session, memories["session"])

        return TurnContext(
            session=session,
            history=history,
            prompt_layers=PromptLayers(
                stable_system="",
                persona_context=persona_context,
                mode_context=mode_context,
                user_context=user_context,
                session_context=session_context,
            ),
        )

    @staticmethod
    def _build_user_context(
        global_profile: str,
        persona_profile: dict | None,
        memories: dict[str, list[str]],
    ) -> str:
        parts: list[str] = []
        if global_profile:
            parts.append(global_profile)
        if memories["user_global"]:
            parts.append("## 用户全局长期记忆\n" + "\n".join(f"- {item}" for item in memories["user_global"]))
        if persona_profile:
            relation_lines = []
            if persona_profile.get("preferred_address"):
                relation_lines.append(f"对用户的固定称呼：{persona_profile['preferred_address']}")
            if persona_profile.get("relationship_stage"):
                relation_lines.append(f"当前关系阶段：{persona_profile['relationship_stage']}")
            try:
                experiences = json.loads(persona_profile.get("shared_experiences", "[]"))
            except (TypeError, json.JSONDecodeError):
                experiences = []
            relation_lines.extend(f"共同经历：{item}" for item in experiences)
            if relation_lines:
                parts.append("## 当前用户与角色的关系\n" + "\n".join(relation_lines))
        if memories["user_persona"]:
            parts.append("## 角色专属长期记忆\n" + "\n".join(f"- {item}" for item in memories["user_persona"]))
        return "\n\n".join(parts)

    @staticmethod
    def _build_session_context(session: SessionContext, memories: list[str]) -> str:
        parts = [f"## 当前会话\n会话 ID：{session.session_id}\n模式：{session.mode}"]
        if session.summary:
            parts.append(f"会话摘要：\n{session.summary}")
        if session.workspace:
            parts.append(f"可信工作区：{session.workspace}")
        if memories:
            parts.append("临时会话记忆：\n" + "\n".join(f"- {item}" for item in memories))
        return "\n\n".join(parts)
