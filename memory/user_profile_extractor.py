"""跨角色、跨模式共享的稳定用户画像提取器。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from memory.chat_db import chat_db
from model.factory import chat_model
from utils.logger_handler import logger


_EXTRACTION_PROMPT = """你是 User Global Profile 提取器。
请从本轮对话中提取用户明确表达、适合跨角色和跨会话长期保存的稳定信息。

只允许提取：
1. display_name：用户明确说出的姓名或希望使用的通用称呼
2. language：语言偏好
3. occupation：职业、专业或长期研究方向
4. stable_interests：稳定兴趣，返回字符串数组
5. preferences：跨场景通用偏好，返回 JSON 对象
6. extra：其他明确、稳定且长期有帮助的信息，返回 JSON 对象

严格规则：
- 只提取用户明确表达的信息，不推测，不从助手回答中提取事实。
- 当前任务、临时状态、工作区、上传文件和本轮待办不属于全局画像。
- 与某个角色的关系、称呼和共同经历不属于全局画像。
- 没有新信息的字段返回空值。
- 只返回 JSON，不要输出 Markdown 或解释。

返回格式：
{{"display_name": "", "language": "", "occupation": "", "stable_interests": [], "preferences": {{}}, "extra": {{}}}}

本轮对话：
用户：{user_msg}
助手：{assistant_msg}"""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text[:120])
    return result


def _dictionary(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


async def _llm_extract(user_msg: str, assistant_msg: str) -> dict[str, Any]:
    """调用模型提取画像；格式化、请求和解析都在异常边界内。"""

    try:
        prompt = _EXTRACTION_PROMPT.format(
            user_msg=user_msg[:800],
            assistant_msg=assistant_msg[:500],
        )
        response = await chat_model.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        text = str(content).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            text = text.rsplit("```", 1)[0].strip()
        result = json.loads(text)
        return result if isinstance(result, dict) else {}
    except Exception as error:
        logger.warning("[ProfileExtractor] LLM 提取失败: %s", error, exc_info=True)
        return {}


async def extract_and_save_profile(
    user_id: str | None,
    user_msg: str,
    assistant_msg: str,
) -> None:
    """提取并合并 User Global Profile，不让画像失败影响主对话。"""

    if not user_id or not user_msg.strip():
        return

    try:
        extracted = await _llm_extract(user_msg, assistant_msg)
        if not extracted:
            return

        existing = await asyncio.to_thread(chat_db.get_global_user_profile, user_id) or {}
        display_name = str(extracted.get("display_name", "")).strip()
        language = str(extracted.get("language", "")).strip() or str(existing.get("language", ""))
        occupation = str(extracted.get("occupation", "")).strip() or str(existing.get("occupation", ""))

        interests = _string_list(existing.get("stable_interests", []))
        for interest in _string_list(extracted.get("stable_interests", [])):
            if interest not in interests:
                interests.append(interest)

        preferences = _dictionary(existing.get("preferences", {}))
        preferences.update(_dictionary(extracted.get("preferences", {})))
        extra = _dictionary(existing.get("extra", {}))
        extra.update(_dictionary(extracted.get("extra", {})))

        has_new_profile_data = any((
            display_name,
            extracted.get("language"),
            extracted.get("occupation"),
            _string_list(extracted.get("stable_interests", [])),
            _dictionary(extracted.get("preferences", {})),
            _dictionary(extracted.get("extra", {})),
        ))
        if not has_new_profile_data:
            return

        await asyncio.to_thread(
            chat_db.upsert_global_user_profile,
            user_id,
            language=language,
            occupation=occupation,
            stable_interests=interests,
            preferences=preferences,
            extra=extra,
        )
        if display_name:
            await asyncio.to_thread(chat_db.update_user_display_name, user_id, display_name)
        logger.info(
            "[ProfileExtractor] 全局画像已更新: user=%s, interests=%d",
            user_id,
            len(interests),
        )
    except Exception as error:
        logger.error("[ProfileExtractor] 画像更新失败: %s", error, exc_info=True)


def schedule_profile_extraction(
    user_id: str | None,
    user_msg: str,
    assistant_msg: str,
) -> asyncio.Task[None]:
    """安全启动后台画像任务，并在任务内部消费所有异常。"""

    async def run_safely() -> None:
        try:
            await extract_and_save_profile(user_id, user_msg, assistant_msg)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("[ProfileExtractor] 后台任务异常: %s", error, exc_info=True)

    return asyncio.create_task(
        run_safely(),
        name=f"profile-extraction:{user_id or 'anonymous'}",
    )


def build_profile_context(user_id: str | None) -> str:
    """构建注入 Prompt 的 User Global Profile 文本。"""

    if not user_id:
        return ""
    profile = chat_db.get_global_user_profile(user_id)
    if not profile:
        return ""

    parts: list[str] = []
    if profile.get("display_name"):
        parts.append(f"姓名或通用称呼：{profile['display_name']}")
    if profile.get("language"):
        parts.append(f"语言偏好：{profile['language']}")
    if profile.get("occupation"):
        parts.append(f"职业或专业：{profile['occupation']}")

    interests = _string_list(profile.get("stable_interests", []))
    if interests:
        parts.append(f"稳定兴趣：{'、'.join(interests)}")

    preferences = _dictionary(profile.get("preferences", {}))
    if preferences:
        rendered = "；".join(f"{key}：{value}" for key, value in preferences.items())
        parts.append(f"通用偏好：{rendered}")

    extra = _dictionary(profile.get("extra", {}))
    if extra:
        rendered = "；".join(f"{key}：{value}" for key, value in extra.items())
        parts.append(f"其他稳定信息：{rendered}")

    if not parts:
        return ""
    return "## 用户全局画像\n" + "\n".join(f"- {part}" for part in parts)
