"""对话执行成功后的统一持久化和分层记忆入口。"""

from __future__ import annotations

import asyncio
import re

from agent.summary import build_history_summary, should_build_summary
from agent.harness_events import HarnessEvent
from memory.chat_db import ChatDB
from memory.session_store import SessionStore
from memory.user_profile_extractor import extract_and_save_profile
from orchestration.models import TurnContext


StreamEvent = HarnessEvent


class TurnFinishHook:
    def __init__(self, database: ChatDB, session_store: SessionStore) -> None:
        self._database = database
        self._session_store = session_store

    async def complete(
        self,
        *,
        context: TurnContext,
        prompt: str,
        events: list[StreamEvent],
    ) -> None:
        response = "".join(
            str(event.data.get("text", ""))
            for event in events
            if event.type == "final_text"
        ).strip()
        if not response:
            return
        session = context.session
        await asyncio.to_thread(self._database.save_pair, session.session_id, prompt, response)
        self._session_store.append_pair(session.session_id, prompt, response)
        history = self._session_store.get_history(session.session_id)
        if should_build_summary(history):
            summary = build_history_summary(history)
            self._session_store.set_agent_summary(session.session_id, summary)
            await asyncio.to_thread(self._database.update_session_summary, session.session_id, summary)

        asyncio.create_task(extract_and_save_profile(session.user_id, prompt, response))
        await self._capture_scoped_memory(context, prompt)

    async def _capture_scoped_memory(self, context: TurnContext, prompt: str) -> None:
        session = context.session
        text = " ".join(prompt.split())
        if re.search(r"(?:我叫|我的名字是|我的职业是|我从事|我主要使用中文)", text):
            await asyncio.to_thread(
                self._database.add_memory,
                scope="user_global",
                user_id=session.user_id,
                content=text,
                source_quote=text,
                confidence=0.9,
                importance=0.8,
            )
            name_match = re.search(r"(?:我叫|我的名字是)\s*([^，。！？,!.?\s]{1,20})", text)
            if name_match:
                await asyncio.to_thread(
                    self._database.update_user_display_name,
                    session.user_id,
                    name_match.group(1),
                )
        if re.search(r"(?:我们约定|以后叫我|你叫我|记住我们|我们一起)", text):
            await asyncio.to_thread(
                self._database.add_memory,
                scope="user_persona",
                user_id=session.user_id,
                persona_id=session.persona_id,
                content=text,
                source_quote=text,
                confidence=0.9,
                importance=0.8,
            )
            address_match = re.search(r"(?:以后叫我|你叫我)\s*([^，。！？,!.?\s]{1,20})", text)
            await asyncio.to_thread(
                self._database.upsert_user_persona_profile,
                session.user_id,
                session.persona_id,
                preferred_address=address_match.group(1) if address_match else None,
                shared_experiences=[text] if "我们" in text else None,
            )
