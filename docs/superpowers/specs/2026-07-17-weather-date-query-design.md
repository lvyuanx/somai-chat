# Weather Date Query Design

## Goal

Allow weather requests to specify a date using Chinese relative expressions such as yesterday, today, and tomorrow, or an
explicit date such as `2026年7月15日`.

## Design

Expose one Agent tool, `get_weather(city, date)`, to keep weather selection simple for the model.

- Without a date or with today, retrieve the existing real-time weather endpoint.
- For a future date within the QWeather daily forecast response, retrieve the daily forecast endpoint and return the matching
  date's normalized conditions.
- For yesterday, any past date, an invalid date, or a date outside the provider forecast response, return the stable message
  `该日期暂无可查询天气数据`.

The tool resolves relative dates against the server's local current date. The model passes the user-supplied date expression to
the tool; date parsing and availability decisions stay in the weather module.

## Data Flow

`Agent -> get_weather(city, date) -> QWeatherClient`.

The client resolves the city as it does today. It uses `/v7/weather/now` for today and `/v7/weather/3d` for a future date.
The client normalizes the selected daily item and the tool hides transport or provider errors behind the existing safe service
error. Expected date availability is returned as stable user-facing data, not treated as an upstream error.

## Testing

Unit tests will cover relative and explicit date parsing, today real-time lookups, forecast lookups, unavailable dates, and
the tool's safe-error behavior. Prompt tests will assert that the declared capability and tool-use guidance include date-based
weather queries.
