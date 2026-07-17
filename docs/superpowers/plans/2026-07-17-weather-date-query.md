# Weather Date Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the weather tool to query current conditions or a requested forecast date using relative or explicit Chinese dates.

**Architecture:** Keep `get_weather` as one Agent tool with an optional `date` parameter. The weather client parses date input, uses
the existing real-time endpoint for today, and uses QWeather's three-day forecast endpoint for future dates. Expected unavailable
dates are returned as stable tool results; provider and network faults remain safe service errors.

**Tech Stack:** Python 3.12, httpx, LangChain tools, pytest, pytest-asyncio.

---

## Files

- `src/somai_chat/weather/client.py`: Date parsing, endpoint selection, daily forecast normalization.
- `src/somai_chat/weather/tool.py`: Optional tool date input and unavailable-date result mapping.
- `src/somai_chat/agent/prompts.py`: Date-aware tool use instructions.
- `tests/unit/test_weather.py`: Client and tool behavior.
- `tests/unit/test_prompts.py`: Runtime capability contract.
- `src/somai_chat/weather/AGENTS.md`: Module data flow and availability boundary.

### Task 1: Add Forecast Lookup to the Weather Client

**Files:** `tests/unit/test_weather.py`, `src/somai_chat/weather/client.py`

- [ ] **Step 1: Write a failing forecast test**

```python
@pytest.mark.asyncio
async def test_weather_client_returns_requested_forecast_day() -> None:
    weather = await client.get_weather("北京", "明天", today=date(2026, 7, 17))
    assert weather == {
        "location": "北京, 北京",
        "forecast_date": "2026-07-18",
        "condition_day": "多云",
    }
```

- [ ] **Step 2: Verify RED**

Run `uv run pytest tests/unit/test_weather.py::test_weather_client_returns_requested_forecast_day -v`.

Expected: FAIL because `get_weather` is absent.

- [ ] **Step 3: Implement the smallest client API**

```python
async def get_weather(
    self, city: str | None = None, date_text: str | None = None, *, today: date | None = None
) -> dict[str, WeatherValue]:
    current_day = today or date.today()
    target_day = self._parse_date(date_text, current_day)
    if target_day == current_day:
        return await self.get_current_weather(city)
    return await self._get_forecast_weather(city, target_day)
```

Implement private helpers for yesterday, today, tomorrow, and `YYYY年M月D日`; call `/v7/weather/3d` and select its matching
`fxDate` item.

- [ ] **Step 4: Verify GREEN**

Run `uv run pytest tests/unit/test_weather.py::test_weather_client_returns_requested_forecast_day -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add src/somai_chat/weather/client.py tests/unit/test_weather.py` followed by
`git commit -m "feat(weather): query daily forecast by date"`.

### Task 2: Return Stable Unavailable-Date Results

**Files:** `tests/unit/test_weather.py`, `src/somai_chat/weather/client.py`, `src/somai_chat/weather/tool.py`

- [ ] **Step 1: Write failing unavailable-date and forwarding tests**

```python
assert await tool.ainvoke({"date": "昨天"}) == {"error": "该日期暂无可查询天气数据"}
assert await tool.ainvoke({"city": "北京", "date": "明天"}) == {
    "location": "北京", "forecast_date": "2026-07-18"
}
```

- [ ] **Step 2: Verify RED**

Run `uv run pytest tests/unit/test_weather.py -k 'unavailable or forwards_city' -v`.

Expected: FAIL because the tool has no date input and no unavailable-date mapping.

- [ ] **Step 3: Add the error boundary and tool argument**

```python
class WeatherDateUnavailableError(ValueError):
    """Raised for dates outside the supported weather data window."""

@tool
async def get_weather(city: str | None = None, date: str | None = None) -> Mapping[str, WeatherValue]:
    try:
        return await weather_client.get_weather(city, date)
    except WeatherDateUnavailableError:
        return {"error": "该日期暂无可查询天气数据"}
    except Exception:
        return {"error": "天气服务暂时不可用，请稍后再试。"}
```

Raise `WeatherDateUnavailableError` for yesterday, malformed date text, dates before today, and dates missing from the forecast
response.

- [ ] **Step 4: Verify GREEN**

Run `uv run pytest tests/unit/test_weather.py -k 'unavailable or forwards_city' -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add src/somai_chat/weather/client.py src/somai_chat/weather/tool.py tests/unit/test_weather.py` followed by
`git commit -m "feat(weather): expose date-aware lookup tool"`.

### Task 3: Update Agent Capability and Module Documentation

**Files:** `tests/unit/test_prompts.py`, `src/somai_chat/agent/prompts.py`, `src/somai_chat/weather/AGENTS.md`

- [ ] **Step 1: Write a failing prompt contract test**

```python
def test_prompt_describes_date_based_weather_queries() -> None:
    assert "指定日期的天气预报" in RUNTIME_CAPABILITIES
    assert "昨天、今天、明天" in RUNTIME_CAPABILITIES
```

- [ ] **Step 2: Verify RED**

Run `uv run pytest tests/unit/test_prompts.py::test_prompt_describes_date_based_weather_queries -v`.

Expected: FAIL because the prompt only declares current weather.

- [ ] **Step 3: Update prompt and AGENTS.md**

```python
RUNTIME_CAPABILITIES = """当前可用能力：文本多轮对话、当前天气和指定日期的天气预报查询。
天气日期可使用昨天、今天、明天或具体日期；仅能返回当前和供应商预报范围内的数据。
..."""
```

Document the single date-aware tool, current versus forecast endpoint selection, and stable unavailable-date response.

- [ ] **Step 4: Verify GREEN**

Run `uv run pytest tests/unit/test_prompts.py::test_prompt_describes_date_based_weather_queries -v`.

Expected: PASS.

- [ ] **Step 5: Commit**

Run `git add src/somai_chat/agent/prompts.py src/somai_chat/weather/AGENTS.md tests/unit/test_prompts.py` followed by
`git commit -m "docs: describe date-based weather queries"`.

### Task 4: Full Verification

- [ ] **Step 1: Run focused tests**

Run `uv run pytest tests/unit/test_weather.py tests/unit/test_prompts.py -v`.

Expected: PASS.

- [ ] **Step 2: Run the quality suite**

Run `make check`.

Expected: Ruff, strict mypy, and all tests PASS.
