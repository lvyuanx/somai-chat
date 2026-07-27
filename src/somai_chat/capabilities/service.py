"""Validate, persist, and publish immutable capability tool snapshots."""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol, cast

import httpx
from cryptography.fernet import InvalidToken
from langchain_core.tools import BaseTool
from pydantic import JsonValue, ValidationError

from somai_chat.admin.credentials import decrypt_key, encrypt_key
from somai_chat.capabilities.models import (
    CapabilityConfiguration,
    CapabilityKey,
    CapabilityNotFoundError,
    CapabilitySecretUnavailableError,
    CapabilitySeed,
    CapabilityState,
    CapabilityUpdate,
    CapabilityValidationError,
    CapabilityView,
    StoredCapability,
    TimeConfiguration,
    WeatherConfiguration,
    WebSearchConfiguration,
)
from somai_chat.time.tool import create_time_tool
from somai_chat.weather.client import QWeatherClient
from somai_chat.weather.tool import create_weather_tool
from somai_chat.web.search import TavilyClient, create_web_search_tool


class CapabilityRepositoryProtocol(Protocol):
    async def seed_missing(self, seeds: Sequence[StoredCapability]) -> None: ...
    async def list(self) -> list[StoredCapability]: ...
    async def update(self, value: StoredCapability) -> StoredCapability | None: ...


def parse_configuration(key: str, value: dict[str, object]) -> CapabilityConfiguration:
    try:
        if key == "weather":
            return WeatherConfiguration.model_validate(value)
        if key == "time":
            return TimeConfiguration.model_validate(value)
        if key == "web_search":
            return WebSearchConfiguration.model_validate(value)
        raise CapabilityNotFoundError(key)
    except ValidationError as error:
        raise CapabilityValidationError("Invalid capability configuration") from error


class CapabilityService:
    def __init__(
        self,
        repository: CapabilityRepositoryProtocol,
        *,
        encryption_secret: str,
        weather_http_client: httpx.AsyncClient,
        search_http_client: httpx.AsyncClient,
    ) -> None:
        self._repository = repository
        self._secret = encryption_secret
        self._weather_http_client = weather_http_client
        self._search_http_client = search_http_client
        self._states: dict[CapabilityKey, CapabilityState] = {}
        self._tools: tuple[BaseTool, ...] = ()
        self._update_lock = asyncio.Lock()

    async def initialize(self, seeds: Sequence[CapabilitySeed]) -> None:
        encrypted = [
            StoredCapability(
                key=seed.key,
                enabled=seed.enabled,
                configuration=seed.configuration,
                encrypted_api_key=encrypt_key(seed.api_key, self._secret) if seed.api_key else None,
            )
            for seed in seeds
        ]
        await self._repository.seed_missing(encrypted)
        states: dict[CapabilityKey, CapabilityState] = {}
        for stored in await self._repository.list():
            api_key = None
            if stored.encrypted_api_key:
                try:
                    api_key = decrypt_key(stored.encrypted_api_key, self._secret)
                except InvalidToken:
                    pass
            states[stored.key] = CapabilityState(
                key=stored.key,
                enabled=stored.enabled,
                configuration=parse_configuration(stored.key, cast(dict[str, object], stored.configuration)),
                api_key=api_key,
                updated_at=stored.updated_at,
            )
        self._states = states
        self._tools = self._build_tools(states)

    def snapshot(self) -> tuple[BaseTool, ...]:
        return self._tools

    async def list_views(self) -> list[CapabilityView]:
        order = ("weather", "time", "web_search")
        return [self._view(self._states[key]) for key in order if key in self._states]

    async def reveal_api_key(self, key: str) -> str:
        state = self._states.get(cast(CapabilityKey, key))
        if state is None:
            raise CapabilityNotFoundError(key)
        if state.api_key is None:
            raise CapabilitySecretUnavailableError(key)
        return state.api_key

    async def update(self, key: str, command: CapabilityUpdate) -> CapabilityView:
        async with self._update_lock:
            typed_key = cast(CapabilityKey, key)
            current = self._states.get(typed_key)
            if current is None:
                raise CapabilityNotFoundError(key)
            configuration = parse_configuration(key, cast(dict[str, object], command.configuration))
            replacement_key = command.api_key.strip() if command.api_key is not None else None
            if command.api_key is not None and not replacement_key:
                raise CapabilityValidationError("API Key must not be blank")
            api_key = None if command.clear_api_key else replacement_key or current.api_key
            if key == "time" and (replacement_key is not None or command.clear_api_key):
                raise CapabilityValidationError("Time capability does not use an API Key")
            if command.enabled and key in {"weather", "web_search"} and api_key is None:
                raise CapabilityValidationError("API Key is required before enabling this capability")
            candidate = replace(current, enabled=command.enabled, configuration=configuration, api_key=api_key)
            states = {**self._states, typed_key: candidate}
            tools = self._build_tools(states)
            stored = await self._repository.update(self._to_stored(candidate))
            if stored is None:
                raise CapabilityNotFoundError(key)
            published = replace(candidate, updated_at=stored.updated_at)
            self._states = {**states, typed_key: published}
            self._tools = tools
            return self._view(published)

    def _to_stored(self, state: CapabilityState) -> StoredCapability:
        return StoredCapability(
            key=state.key,
            enabled=state.enabled,
            configuration=cast(dict[str, JsonValue], state.configuration.model_dump(mode="json")),
            encrypted_api_key=encrypt_key(state.api_key, self._secret) if state.api_key else None,
            updated_at=state.updated_at,
        )

    @staticmethod
    def _view(state: CapabilityState) -> CapabilityView:
        masked = f"••••••••{state.api_key[-4:]}" if state.api_key else None
        return CapabilityView(
            key=state.key,
            enabled=state.enabled,
            configuration=cast(dict[str, JsonValue], state.configuration.model_dump(mode="json")),
            api_key_masked=masked,
            can_reveal_api_key=state.api_key is not None,
            updated_at=state.updated_at,
        )

    def _build_tools(self, states: dict[CapabilityKey, CapabilityState]) -> tuple[BaseTool, ...]:
        tools: list[BaseTool] = []
        weather = states.get("weather")
        if weather and weather.enabled and weather.api_key and isinstance(weather.configuration, WeatherConfiguration):
            tools.append(
                create_weather_tool(
                    QWeatherClient(
                        self._weather_http_client,
                        api_host=str(weather.configuration.api_host),
                        api_key=weather.api_key,
                        timeout_seconds=weather.configuration.timeout_seconds,
                    )
                )
            )
        time_state = states.get("time")
        if time_state and time_state.enabled:
            tools.append(create_time_tool())
        search = states.get("web_search")
        if search and search.enabled and search.api_key and isinstance(search.configuration, WebSearchConfiguration):
            tools.append(
                create_web_search_tool(
                    TavilyClient(
                        self._search_http_client,
                        api_key=search.api_key,
                        api_host=str(search.configuration.api_host),
                        timeout_seconds=search.configuration.timeout_seconds,
                        max_results=search.configuration.max_results,
                    )
                )
            )
        return tuple(tools)
