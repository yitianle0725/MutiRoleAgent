"""评测报告时间字段工具。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def report_timestamps() -> dict[str, str]:
    """返回机器可解析的 UTC 时间和可读的北京时间。"""
    now = datetime.now(timezone.utc)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_beijing": now.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
    }
