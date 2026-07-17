import httpx
import pytest

from somai_chat.weather.client import QWeatherClient
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
async def test_weather_tool_defaults_to_wuhan_and_hides_upstream_failures() -> None:
    class WeatherClient:
        async def get_current_weather(self, city: str | None = None) -> dict[str, str]:
            if city == "失败城市":
                raise httpx.ConnectError("private upstream detail")
            return {"location": city or "武汉", "condition": "晴"}

    tool = create_weather_tool(WeatherClient())

    assert await tool.ainvoke({}) == {"location": "武汉", "condition": "晴"}
    assert await tool.ainvoke({"city": "失败城市"}) == {"error": "天气服务暂时不可用，请稍后再试。"}
