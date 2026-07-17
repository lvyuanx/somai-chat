"""QWeather service adapter."""

from collections.abc import Mapping

import httpx

DEFAULT_CITY = "武汉"
type WeatherValue = str | float


class QWeatherClient:
    """Resolve a city then retrieve its current QWeather conditions."""

    def __init__(self, http_client: httpx.AsyncClient, *, api_host: str, api_key: str) -> None:
        self._http_client = http_client
        self._api_host = api_host.rstrip("/")
        self._headers = {"X-QW-Api-Key": api_key}

    async def get_current_weather(self, city: str | None = None) -> dict[str, WeatherValue]:
        """Return normalized current weather, defaulting to Wuhan when city is omitted."""
        resolved_city = city.strip() if city is not None else ""
        location = await self._lookup_city(resolved_city or DEFAULT_CITY)
        location_id = self._required_text(location, "id")
        response = await self._http_client.get(
            f"{self._api_host}/v7/weather/now",
            params={"location": location_id, "lang": "zh", "unit": "m"},
            headers=self._headers,
        )
        response.raise_for_status()
        payload = self._successful_payload(response.json())
        current = self._mapping(payload.get("now"), "Weather service returned no current conditions")
        return {
            "location": self._location_label(location),
            "observed_at": self._required_text(current, "obsTime"),
            "temperature_celsius": self._required_number(current, "temp"),
            "apparent_temperature_celsius": self._required_number(current, "feelsLike"),
            "condition": self._required_text(current, "text"),
            "wind_speed_kmh": self._required_number(current, "windSpeed"),
        }

    async def _lookup_city(self, city: str) -> Mapping[str, object]:
        response = await self._http_client.get(
            f"{self._api_host}/geo/v2/city/lookup",
            params={"location": city, "lang": "zh", "number": 1},
            headers=self._headers,
        )
        response.raise_for_status()
        payload = self._successful_payload(response.json())
        locations = payload.get("location")
        if not isinstance(locations, list) or not locations:
            raise ValueError("Location was not found")
        return self._mapping(locations[0], "Weather service returned invalid location data")

    @staticmethod
    def _successful_payload(value: object) -> Mapping[str, object]:
        payload = QWeatherClient._mapping(value, "Weather service returned invalid data")
        if payload.get("code") != "200":
            raise ValueError("Weather service request was rejected")
        return payload

    @staticmethod
    def _mapping(value: object, error_message: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError(error_message)
        return value

    @staticmethod
    def _required_number(value: Mapping[str, object], key: str) -> float:
        number = value.get(key)
        if isinstance(number, str):
            try:
                return float(number)
            except ValueError:
                pass
        if isinstance(number, int | float):
            return float(number)
        raise ValueError("Weather service returned incomplete data")

    @staticmethod
    def _required_text(value: Mapping[str, object], key: str) -> str:
        text = value.get(key)
        if not isinstance(text, str) or not text:
            raise ValueError("Weather service returned incomplete data")
        return text

    @staticmethod
    def _location_label(location: Mapping[str, object]) -> str:
        name = QWeatherClient._required_text(location, "name")
        province = location.get("adm1")
        return f"{name}, {province}" if isinstance(province, str) and province else name
