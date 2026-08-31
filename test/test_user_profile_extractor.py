from __future__ import annotations

import asyncio

from memory.chat_db import ChatDB
from memory import user_profile_extractor as extractor


class _ProfileModel:
    def __init__(self) -> None:
        self.prompt = ""

    async def ainvoke(self, prompt: str):
        self.prompt = prompt

        class Response:
            content = (
                '{"display_name":"天乐","language":"中文",'
                '"occupation":"软件工程师","stable_interests":["动漫","Agent"],'
                '"preferences":{"回答风格":"简洁"},'
                '"extra":{"常用技术":"Python"}}'
            )

        return Response()


def test_global_profile_prompt_and_persistence(tmp_path, monkeypatch):
    database = ChatDB(str(tmp_path / "chat.db"))
    database.init_db()
    database.create_session(
        "session-1",
        user_id="user-1",
        persona_id="cyrene",
        mode="chat",
    )
    model = _ProfileModel()
    monkeypatch.setattr(extractor, "chat_db", database)
    monkeypatch.setattr(extractor, "chat_model", model)

    asyncio.run(extractor.extract_and_save_profile(
        "user-1",
        "我叫天乐，是软件工程师，喜欢动漫和 Agent。",
        "很高兴认识你。",
    ))

    assert '{"display_name": ""' in model.prompt
    profile = database.get_global_user_profile("user-1")
    assert profile is not None
    assert profile["display_name"] == "天乐"
    assert profile["language"] == "中文"
    assert profile["occupation"] == "软件工程师"
    assert profile["stable_interests"] == ["动漫", "Agent"]
    assert profile["preferences"] == {"回答风格": "简洁"}
    assert "扫地" not in extractor._EXTRACTION_PROMPT
    assert "软件工程师" in extractor.build_profile_context("user-1")


def test_background_profile_failure_is_consumed(monkeypatch, caplog):
    async def fail(*args, **kwargs):
        raise RuntimeError("画像服务暂时不可用")

    monkeypatch.setattr(extractor, "extract_and_save_profile", fail)

    async def run():
        task = extractor.schedule_profile_extraction("user-1", "消息", "回答")
        await task

    asyncio.run(run())
    assert "后台任务异常" in caplog.text
