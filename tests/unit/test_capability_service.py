from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest

from somai_chat.capabilities.models import (
    CapabilitySecretUnavailableError,
    CapabilitySeed,
    CapabilityUpdate,
    CapabilityValidationError,
    StoredCapability,
)
from somai_chat.capabilities.service import CapabilityService


class MemoryRepository:
    def __init__(self, existing: list[StoredCapability] | None = None) -> None:
        self.values = {item.key: item for item in existing or []}
        self.seeded_keys: set[str] = set()

    async def seed_missing(self, seeds: list[StoredCapability]) -> None:
        for seed in seeds:
            if seed.key not in self.values:
                self.values[seed.key] = replace(seed, updated_at=datetime.now(UTC))
                self.seeded_keys.add(seed.key)

    async def list(self) -> list[StoredCapability]:
        return sorted(self.values.values(), key=lambda item: item.key)

    async def update(self, value: StoredCapability) -> StoredCapability | None:
        if value.key not in self.values:
            return None
        saved = replace(value, updated_at=datetime.now(UTC))
        self.values[value.key] = saved
        return saved


def seeds(weather_key: str | None = "weather-old") -> list[CapabilitySeed]:
    return [
        CapabilitySeed(
            key="weather",
            enabled=weather_key is not None,
            configuration={"api_host": "https://weather.example", "timeout_seconds": 5},
            api_key=weather_key,
        ),
        CapabilitySeed(key="time", enabled=True, configuration={}, api_key=None),
        CapabilitySeed(
            key="web_search",
            enabled=False,
            configuration={"api_host": "https://search.example", "timeout_seconds": 10, "max_results": 5},
            api_key=None,
        ),
    ]


async def make_service(repository: MemoryRepository, weather_key: str | None = "weather-old") -> CapabilityService:
    service = CapabilityService(
        repository,
        encryption_secret="capability-encryption",
        weather_http_client=httpx.AsyncClient(trust_env=False),
        search_http_client=httpx.AsyncClient(trust_env=False),
    )
    await service.initialize(seeds(weather_key))
    return service


@pytest.mark.asyncio
async def test_initialization_seeds_only_missing_capabilities() -> None:
    existing = StoredCapability(
        key="time", enabled=False, configuration={}, encrypted_api_key=None, updated_at=datetime.now(UTC)
    )
    repository = MemoryRepository([existing])
    service = await make_service(repository)

    views = {view.key: view for view in await service.list_views()}

    assert repository.seeded_keys == {"weather", "web_search"}
    assert views["time"].enabled is False


@pytest.mark.asyncio
async def test_enabled_weather_requires_api_key() -> None:
    service = await make_service(MemoryRepository(), weather_key=None)

    with pytest.raises(CapabilityValidationError, match="API Key"):
        await service.update(
            "weather",
            CapabilityUpdate(
                enabled=True,
                configuration={"api_host": "https://weather.example", "timeout_seconds": 5},
            ),
        )


@pytest.mark.asyncio
async def test_update_preserves_replaces_and_clears_api_key() -> None:
    service = await make_service(MemoryRepository())
    configuration = {"api_host": "https://weather.example", "timeout_seconds": 5}

    preserved = await service.update("weather", CapabilityUpdate(enabled=True, configuration=configuration))
    await service.update("weather", CapabilityUpdate(enabled=True, configuration=configuration, api_key="weather-new"))
    revealed = await service.reveal_api_key("weather")
    cleared = await service.update(
        "weather", CapabilityUpdate(enabled=False, configuration=configuration, clear_api_key=True)
    )

    assert preserved.api_key_masked == "••••••••-old"
    assert revealed == "weather-new"
    assert cleared.api_key_masked is None


@pytest.mark.asyncio
async def test_snapshot_contains_only_enabled_tools() -> None:
    service = await make_service(MemoryRepository())
    await service.update("time", CapabilityUpdate(enabled=False, configuration={}))
    await service.update(
        "web_search",
        CapabilityUpdate(
            enabled=True,
            configuration={"api_host": "https://search.example", "timeout_seconds": 10, "max_results": 5},
            api_key="search-key",
        ),
    )

    assert {tool.name for tool in service.snapshot()} == {"get_weather", "web_search"}


@pytest.mark.asyncio
async def test_invalid_ciphertext_does_not_publish_or_reveal_tool() -> None:
    repository = MemoryRepository(
        [
            StoredCapability(
                key="weather",
                enabled=True,
                configuration={"api_host": "https://weather.example", "timeout_seconds": 5},
                encrypted_api_key="invalid",
                updated_at=datetime.now(UTC),
            )
        ]
    )
    service = await make_service(repository)

    assert "get_weather" not in {tool.name for tool in service.snapshot()}
    with pytest.raises(CapabilitySecretUnavailableError):
        await service.reveal_api_key("weather")
