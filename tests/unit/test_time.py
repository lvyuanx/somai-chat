from datetime import UTC, datetime

import pytest

from somai_chat.time.tool import create_time_tool


@pytest.mark.asyncio
async def test_time_tool_returns_current_china_standard_time() -> None:
    tool = create_time_tool(now=lambda: datetime(2026, 7, 17, 6, 30, tzinfo=UTC))

    assert await tool.ainvoke({}) == {
        "date": "2026-07-17",
        "weekday": "星期五",
        "time": "14:30:00",
        "timezone": "中国标准时间",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("days_from_today, expected_date", [(1, "2026-07-18"), (2, "2026-07-19")])
async def test_time_tool_applies_future_day_offset(days_from_today: int, expected_date: str) -> None:
    tool = create_time_tool(now=lambda: datetime(2026, 7, 17, 6, 30, tzinfo=UTC))

    result = await tool.ainvoke({"days_from_today": days_from_today})

    assert result["date"] == expected_date
    assert result["time"] == "14:30:00"


@pytest.mark.asyncio
async def test_time_tool_rejects_past_day_offset() -> None:
    tool = create_time_tool(now=lambda: datetime(2026, 7, 17, 6, 30, tzinfo=UTC))

    assert await tool.ainvoke({"days_from_today": -1}) == {"error": "仅支持查询当前或未来的时间"}
