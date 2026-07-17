# China Standard Time Query Design

## Goal

Enable SOMAI to obtain the current China Standard Time and the time on a future relative day,
including tomorrow, the day after tomorrow, and two days after today.

## Chosen Approach

Introduce an independent LangChain time tool rather than extending the weather tool. The tool has
no external service dependency and always uses the `Asia/Shanghai` time zone.

## Interface

`get_current_time(days_from_today=0)` accepts a non-negative whole-day offset. It returns the
complete local date and time for China Standard Time, including the calendar date, weekday, and
time to seconds. An offset of `0` returns the current time; `1` and `2` return the same wall-clock
time tomorrow and the day after tomorrow.

Negative, non-integer, and otherwise invalid offsets return a stable validation message rather than
silently calculating a past date.

## Integration

The composition root registers the time tool alongside the weather tool when it builds the
conversation graph. The runtime capability prompt states that time questions must use this tool and
that results are always China Standard Time. The model maps natural-language relative dates to the
numeric offset supplied to the tool.

## Tests

Unit tests will freeze the source time to assert the returned China Standard Time, day offsets, and
invalid-offset behavior. Prompt and composition tests will verify the announced capability and tool
registration. The existing graph tests remain the behavioral confirmation that requested tools run
before the model's final response.

## Scope

This feature does not add arbitrary time zones, historical dates, scheduled reminders, or any
external time API.
