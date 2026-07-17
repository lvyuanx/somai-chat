"""LangChain tool adapter for China Standard Time lookups."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool

_CHINA_STANDARD_TIME = ZoneInfo("Asia/Shanghai")
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def create_time_tool(now: Callable[[], datetime] | None = None) -> BaseTool:
    """Create a tool that returns the current or future China Standard Time."""

    clock = now or (lambda: datetime.now(UTC))

    @tool
    async def get_current_time(days_from_today: int = 0) -> Mapping[str, str]:
        """查询中国标准时间；days_from_today 为从今天起的非负整日偏移。"""
        if days_from_today < 0:
            return {"error": "仅支持查询当前或未来的时间"}
        current = clock().astimezone(_CHINA_STANDARD_TIME) + timedelta(days=days_from_today)
        return {
            "date": current.date().isoformat(),
            "weekday": _WEEKDAYS[current.weekday()],
            "time": current.strftime("%H:%M:%S"),
            "timezone": "中国标准时间",
        }

    return get_current_time
