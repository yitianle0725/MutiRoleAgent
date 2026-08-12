"""
用户画像提取器（L0 长期记忆）
============================
从对话中自动提取用户信息（设备型号、偏好、问题记录），
写入 user_profile 表，实现跨会话记忆。

提取策略
--------
- **关键词快速提取**：设备型号/品牌等明显信息直接用规则匹配
- **LLM 深度提取**：偏好/习惯等隐含信息调用轻量 prompt 提取
- **去重合并**：新信息与已有画像合并，不重复写入

使用方式::

    from agent.user_profile_extractor import extract_and_save_profile

    # 在每轮对话后调用（不阻塞主流程）
    await extract_and_save_profile(user_id, user_msg, assistant_msg)
"""

import json
import re

from db.chat_db import chat_db
from model.factory import chat_model
from utils.logger_handler import logger


# ==================== 关键词快速提取 ====================

# 常见扫地机器人品牌/型号模式
_DEVICE_PATTERNS: list[re.Pattern] = [
    re.compile(r'(石头\s*[A-Za-z]?\d+)'),
    re.compile(r'(科沃斯\s*[A-Za-z]?\d+)'),
    re.compile(r'(小米\s*(?:扫地|扫拖)?\s*[A-Za-z]?\d*)'),
    re.compile(r'(追觅\s*[A-Za-z]?\d+)'),
    re.compile(r'(云鲸\s*[A-Za-z]?\d+)'),
    re.compile(r'(iRobot\s*[A-Za-z]?\d+)'),
    re.compile(r'(美的\s*[A-Za-z]?\d+)'),
    re.compile(r'(海尔\s*[A-Za-z]?\d+)'),
    re.compile(r'型号[是为:：]?\s*([A-Za-z0-9\-]+)'),
    re.compile(r'买了[一个台]?\s*(\S{2,10}?(?:机器人|扫地机|扫拖))'),
]

# 偏好关键词
_PREFERENCE_KEYWORDS: list[str] = [
    "静音", "强力", "标准", "节能", "定时", "预约",
    "全屋", "单间", "选区", "禁区", "虚拟墙",
    "每天", "每周", "上午", "下午", "早上", "晚上",
    "湿拖", "干拖", "扫拖", "只扫", "只拖",
]


def _extract_device_model(text: str) -> str | None:
    """从文本中快速提取设备型号。"""
    for pattern in _DEVICE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def _extract_preferences_quick(text: str) -> list[str]:
    """快速提取用户偏好关键词。"""
    found = []
    for kw in _PREFERENCE_KEYWORDS:
        if kw in text:
            found.append(kw)
    return found


# ==================== LLM 深度提取 ====================

_EXTRACTION_PROMPT = """你是一个用户画像提取助手。从以下对话中提取用户关于扫地机器人的关键信息。
只提取以下字段（无信息则返回空值）：

1. device_model: 用户使用的设备品牌和型号
2. preferences: 用户提到的使用偏好（清洁模式、时间偏好、频率等），用逗号分隔
3. issues: 用户当前遇到的问题或故障描述
4. extra: 其他值得记住的信息（家庭成员、宠物、房屋面积等）

返回纯 JSON 格式（不要 markdown 标记）：
{"device_model": "", "preferences": "", "issues": "", "extra": ""}

对话内容：
用户：{user_msg}
助手：{assistant_msg}"""


async def _llm_extract(user_msg: str, assistant_msg: str) -> dict:
    """调用 LLM 深度提取用户画像信息。"""
    prompt = _EXTRACTION_PROMPT.format(
        user_msg=user_msg[:500],
        assistant_msg=assistant_msg[:300],
    )
    try:
        response = await chat_model.ainvoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        # 清理可能的 markdown 标记
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("\n", 1)[0] if "\n" in text else text
            text = text.replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        logger.warning(f"[ProfileExtractor] LLM 提取失败: {e}")
        return {}


# ==================== 主入口 ====================

async def extract_and_save_profile(
    user_id: str | None,
    user_msg: str,
    assistant_msg: str,
):
    """从一轮对话中提取用户画像并保存到 SQLite。

    合并策略：
    - device_model: 新值覆盖旧值（用户可能换设备）
    - preferences: 合并去重（累积用户偏好）
    - issues_log: 追加当前问题（保留历史问题记录）
    - extra: 合并

    Args:
        user_id: 用户 ID，None 则跳过。
        user_msg: 用户本轮消息。
        assistant_msg: 助手本轮回复。
    """
    if not user_id or not user_msg:
        return

    # 1) 快速关键词提取
    device = _extract_device_model(user_msg)
    quick_prefs = _extract_preferences_quick(user_msg)

    # 2) LLM 深度提取（异步，不影响主流程）
    llm_result = await _llm_extract(user_msg, assistant_msg)

    # 3) 合并结果
    final_device = device or llm_result.get("device_model", "")

    all_prefs = set(quick_prefs)
    llm_prefs = llm_result.get("preferences", "")
    if llm_prefs:
        for p in llm_prefs.replace("，", ",").split(","):
            p = p.strip()
            if p:
                all_prefs.add(p)
    final_prefs = json.dumps(
        sorted(all_prefs), ensure_ascii=False
    )

    # issues: 追加到历史
    current_issue = llm_result.get("issues", "")
    existing = chat_db.get_user_profile(user_id)
    if existing:
        try:
            issues_log = json.loads(existing["issues_log"])
        except (json.JSONDecodeError, TypeError):
            issues_log = []
    else:
        issues_log = []

    if current_issue and current_issue not in issues_log:
        issues_log.append(current_issue)
        # 最多保留 20 条问题记录
        if len(issues_log) > 20:
            issues_log = issues_log[-20:]

    final_issues = json.dumps(issues_log, ensure_ascii=False)

    # extra: LLM 提取的额外信息合并
    final_extra = llm_result.get("extra", "")
    if existing and existing.get("extra"):
        try:
            existing_extra = json.loads(existing["extra"])
        except (json.JSONDecodeError, TypeError):
            existing_extra = {}
        if final_extra:
            if isinstance(existing_extra, dict):
                existing_extra["_latest"] = final_extra
            final_extra = json.dumps(existing_extra, ensure_ascii=False)

    # 4) 写入数据库（仅在有新信息时）
    if final_device or all_prefs or current_issue or final_extra:
        chat_db.upsert_user_profile(
            user_id=user_id,
            device_model=final_device or None,
            preferences=final_prefs,
            issues_log=final_issues,
            extra=final_extra or None,
        )
        logger.info(
            f"[ProfileExtractor] 用户画像已更新: user={user_id}, "
            f"device={final_device[:20] if final_device else 'N/A'}, "
            f"prefs={len(all_prefs)}个"
        )


def build_profile_context(user_id: str | None) -> str:
    """构建用户画像上下文文本，用于注入 system prompt。

    Args:
        user_id: 用户 ID，None 或画像不存在则返回空字符串。

    Returns:
        格式化的用户画像文本，如 "已知用户信息：设备=石头P10，偏好=静音/定时..."
    """
    if not user_id:
        return ""

    profile = chat_db.get_user_profile(user_id)
    if not profile:
        return ""

    parts: list[str] = []

    if profile.get("device_model"):
        parts.append(f"用户设备：{profile['device_model']}")

    try:
        prefs = json.loads(profile.get("preferences", "[]"))
        if prefs:
            parts.append(f"使用偏好：{'、'.join(prefs)}")
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"[ProfileExtractor] 偏好 JSON 解析失败: {profile.get('preferences', '')[:50]}")

    try:
        issues = json.loads(profile.get("issues_log", "[]"))
        if issues:
            recent_issues = issues[-3:]
            parts.append(f"近期问题：{'；'.join(recent_issues)}")
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"[ProfileExtractor] 问题日志 JSON 解析失败")

    if profile.get("extra"):
        try:
            extra = json.loads(profile["extra"]) if isinstance(profile["extra"], str) else profile["extra"]
            if isinstance(extra, dict):
                latest = extra.pop("_latest", "")
                if latest:
                    parts.append(f"其他信息：{latest}")
        except (json.JSONDecodeError, TypeError):
            logger.warning("[ProfileExtractor] extra JSON 解析失败")

    if not parts:
        return ""

    return "## 已知用户信息\n" + "\n".join(f"- {p}" for p in parts)
