"""LangChain tool adapter for weather lookups."""

from collections.abc import Mapping
from typing import Protocol

from langchain_core.tools import BaseTool, tool

from somai_chat.weather.client import WeatherDateUnavailableError, WeatherValue


class WeatherClient(Protocol):
    """The weather client surface needed by the Agent tool."""

    async def get_weather(
        self, city: str | None = None, date_text: str | None = None
    ) -> Mapping[str, WeatherValue]: ...


def create_weather_tool(weather_client: WeatherClient) -> BaseTool:
    """Create a weather tool that keeps third-party failure details private."""

    @tool
    async def get_weather(city: str | None = None, date: str | None = None) -> Mapping[str, WeatherValue]:
        """查询指定城市在今天或指定日期的天气。未提供城市时，默认查询武汉。"""
        try:
            return await weather_client.get_weather(city, date)
        except WeatherDateUnavailableError:
            return {"error": "该日期暂无可查询天气数据"}
        except Exception:
            return {"error": "天气服务暂时不可用，请稍后再试。"}

    return get_weather
