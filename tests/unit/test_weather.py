from datetime import date

import httpx
import pytest

from somai_chat.weather.client import QWeatherClient, WeatherDateUnavailableError
from somai_chat.weather.tool import create_weather_tool


@pytest.mark.asyncio
async def test_weather_client_resolves_city_and_returns_current_conditions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-QW-Api-Key"] == "weather-key"
        if request.url.path == "/geo/v2/city/lookup":
            assert request.url.params["location"] == "北京"
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [{"name": "北京", "adm1": "北京", "id": "101010100"}],
                },
            )
        assert request.url.path == "/v7/weather/now"
        assert request.url.params["location"] == "101010100"
        assert request.url.params["lang"] == "zh"
        return httpx.Response(
            200,
            json={
                "code": "200",
                "now": {
                    "obsTime": "2026-07-17T10:00+08:00",
                    "temp": "28",
                    "feelsLike": "30",
                    "text": "阴",
                    "windSpeed": "12",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = QWeatherClient(http_client, api_host="https://example.qweatherapi.com", api_key="weather-key")
        weather = await client.get_current_weather("北京")

    assert weather == {
        "location": "北京, 北京",
        "observed_at": "2026-07-17T10:00+08:00",
        "temperature_celsius": 28.0,
        "apparent_temperature_celsius": 30.0,
        "condition": "阴",
        "wind_speed_kmh": 12.0,
    }


@pytest.mark.asyncio
async def test_weather_client_uses_wuhan_when_city_is_not_provided() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/geo/v2/city/lookup":
            assert request.url.params["location"] == "武汉"
            return httpx.Response(
                200,
                json={"code": "200", "location": [{"name": "武汉", "adm1": "湖北", "id": "101200101"}]},
            )
        return httpx.Response(
            200,
            json={
                "code": "200",
                "now": {
                    "obsTime": "2026-07-17T10:00+08:00",
                    "temp": "31",
                    "feelsLike": "36",
                    "text": "晴",
                    "windSpeed": "8",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = QWeatherClient(http_client, api_host="https://example.qweatherapi.com", api_key="weather-key")
        weather = await client.get_current_weather()

    assert weather["location"] == "武汉, 湖北"


@pytest.mark.asyncio
async def test_weather_client_returns_requested_forecast_day() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/geo/v2/city/lookup":
            return httpx.Response(
                200,
                json={
                    "code": "200",
                    "location": [{"name": "北京", "adm1": "北京", "id": "101010100"}],
                },
            )
        assert request.url.path == "/v7/weather/3d"
        assert request.url.params["location"] == "101010100"
        assert request.url.params["lang"] == "zh"
        return httpx.Response(
            200,
            json={
                "code": "200",
                "daily": [
                    {"fxDate": "2026-07-17", "tempMin": "26", "tempMax": "33", "textDay": "晴", "windSpeedDay": "8"},
                    {
                        "fxDate": "2026-07-18",
                        "tempMin": "25",
                        "tempMax": "31",
                        "textDay": "多云",
                        "windSpeedDay": "10",
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = QWeatherClient(http_client, api_host="https://example.qweatherapi.com", api_key="weather-key")
        weather = await client.get_weather("北京", "明天", today=date(2026, 7, 17))

    assert weather == {
        "location": "北京, 北京",
        "forecast_date": "2026-07-18",
        "minimum_temperature_celsius": 25.0,
        "maximum_temperature_celsius": 31.0,
        "condition_day": "多云",
        "wind_speed_kmh": 10.0,
    }


@pytest.mark.asyncio
async def test_weather_tool_defaults_to_wuhan_and_hides_upstream_failures() -> None:
    class WeatherClient:
        async def get_weather(self, city: str | None = None, date_text: str | None = None) -> dict[str, str]:
            del date_text
            if city == "失败城市":
                raise httpx.ConnectError("private upstream detail")
            return {"location": city or "武汉", "condition": "晴"}

    tool = create_weather_tool(WeatherClient())

    assert await tool.ainvoke({}) == {"location": "武汉", "condition": "晴"}
    assert await tool.ainvoke({"city": "失败城市"}) == {"error": "天气服务暂时不可用，请稍后再试。"}


@pytest.mark.asyncio
async def test_weather_tool_returns_unavailable_message_for_past_date() -> None:
    class WeatherClient:
        async def get_weather(self, city: str | None = None, date_text: str | None = None) -> dict[str, str]:
            del city
            if date_text == "昨天":
                raise WeatherDateUnavailableError("Requested date is in the past")
            return {"location": "武汉"}

    tool = create_weather_tool(WeatherClient())

    assert await tool.ainvoke({"date": "昨天"}) == {"error": "该日期暂无可查询天气数据"}


@pytest.mark.asyncio
async def test_weather_tool_forwards_city_and_date() -> None:
    class WeatherClient:
        async def get_weather(self, city: str | None = None, date_text: str | None = None) -> dict[str, str]:
            return {"location": city or "武汉", "date": date_text or "今天"}

    tool = create_weather_tool(WeatherClient())

    assert await tool.ainvoke({"city": "北京", "date": "明天"}) == {"location": "北京", "date": "明天"}
