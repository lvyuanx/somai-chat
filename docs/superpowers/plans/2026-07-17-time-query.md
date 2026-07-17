# China Standard Time Query Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow SOMAI to answer current and future relative-day time questions using China Standard Time.

**Architecture:** Add a focused `time` module containing a LangChain tool with an injectable clock for deterministic tests. The composition root registers it beside the weather tool, while the system prompt makes its fixed time zone and required use explicit.

**Tech Stack:** Python 3.12, standard-library `datetime` and `zoneinfo`, LangChain tools, pytest, Ruff, mypy.

---

## File Structure

- Create: `src/somai_chat/time/tool.py` - China Standard Time lookup and LangChain adapter.
- Create: `src/somai_chat/time/__init__.py` - package marker.
- Create: `src/somai_chat/time/AGENTS.md` - module responsibilities and public interface.
- Create: `tests/unit/test_time.py` - deterministic tool behavior tests.
- Modify: `src/somai_chat/main.py` - register the time tool with the graph.
- Modify: `src/somai_chat/agent/prompts.py` - expose the capability and invocation requirement.
- Modify: `tests/unit/test_prompts.py` - verify the prompt contract.
- Modify: `src/somai_chat/agent/AGENTS.md` - document the additional controlled tool.
- Modify: `src/somai_chat/AGENTS.md` - document time-tool composition.

### Task 1: Add the China Standard Time tool

**Files:**
- Create: `tests/unit/test_time.py`
- Create: `src/somai_chat/time/__init__.py`
- Create: `src/somai_chat/time/tool.py`
- Create: `src/somai_chat/time/AGENTS.md`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_time.py -v`

Expected: FAIL during collection because `somai_chat.time.tool` does not exist.

- [ ] **Step 3: Implement the minimal tool**

```python
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.tools import BaseTool, tool

_CHINA_STANDARD_TIME = ZoneInfo("Asia/Shanghai")
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def create_time_tool(now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> BaseTool:
    @tool
    async def get_current_time(days_from_today: int = 0) -> Mapping[str, str]:
        """查询中国标准时间；days_from_today 为从今天起的非负整日偏移。"""
        if days_from_today < 0:
            return {"error": "仅支持查询当前或未来的时间"}
        current = now().astimezone(_CHINA_STANDARD_TIME) + timedelta(days=days_from_today)
        return {
            "date": current.date().isoformat(),
            "weekday": _WEEKDAYS[current.weekday()],
            "time": current.strftime("%H:%M:%S"),
            "timezone": "中国标准时间",
        }

    return get_current_time
```

`src/somai_chat/time/__init__.py` contains only the package docstring. `AGENTS.md` documents the fixed time zone, injectable clock, public factory, and that negative offsets return the stable error response.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_time.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/somai_chat/time tests/unit/test_time.py
git commit -m "feat(time): add China Standard Time lookup tool"
```

### Task 2: Register and announce the tool

**Files:**
- Modify: `src/somai_chat/main.py`
- Modify: `src/somai_chat/agent/prompts.py`
- Modify: `tests/unit/test_prompts.py`
- Modify: `src/somai_chat/agent/AGENTS.md`
- Modify: `src/somai_chat/AGENTS.md`

- [ ] **Step 1: Write the failing prompt contract test**

```python
def test_prompt_separates_stable_identity_from_runtime_capabilities() -> None:
    assert "中国标准时间" in RUNTIME_CAPABILITIES
    assert "必须调用时间工具" in RUNTIME_CAPABILITIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_prompts.py::test_prompt_separates_stable_identity_from_runtime_capabilities -v`

Expected: FAIL because the time capability is absent.

- [ ] **Step 3: Wire the tool and update the prompt**

```python
from somai_chat.time.tool import create_time_tool

# Build the graph with both controlled runtime tools.
build_conversation_graph(
    model,
    tools=[create_weather_tool(weather_client), create_time_tool()],
)
```

Append the following capability contract to `RUNTIME_CAPABILITIES`:

```text
可查询当前及未来相对日期的中国标准时间；“明天”和“后天”分别传入一日和两日偏移。
回答时间问题前，必须调用时间工具，不能依据记忆或自行计算当前时间。
```

Update both affected `AGENTS.md` files to state that the composition root injects the time tool and that Agent tool extensions must update the runtime capability contract.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `uv run pytest tests/unit/test_prompts.py tests/unit/test_time.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/somai_chat/main.py src/somai_chat/agent/prompts.py tests/unit/test_prompts.py \
  src/somai_chat/agent/AGENTS.md src/somai_chat/AGENTS.md
git commit -m "feat(agent): expose China Standard Time queries"
```

### Task 3: Verify the integrated change

**Files:**
- Modify: `docs/superpowers/plans/2026-07-17-time-query.md` - mark completed steps after verification.

- [ ] **Step 1: Run formatting, static checks, and tests**

Run: `make format && make lint && make typecheck && make test`

Expected: all commands exit successfully.

- [ ] **Step 2: Review the final diff**

Run: `git diff HEAD~2..HEAD --check && git status --short`

Expected: no whitespace errors and no unintended files.

- [ ] **Step 3: Commit the completed plan checklist**

```bash
git add docs/superpowers/plans/2026-07-17-time-query.md
git commit -m "docs: record time query implementation"
```
