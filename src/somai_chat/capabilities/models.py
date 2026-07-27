"""Fixed capability configuration and boundary models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, JsonValue, model_validator

type CapabilityKey = Literal["weather", "time", "web_search"]


class CapabilityError(Exception):
    """Base error for safe capability operations."""


class CapabilityNotFoundError(CapabilityError):
    """Raised for unsupported capability keys."""


class CapabilityValidationError(CapabilityError):
    """Raised when a complete capability configuration is invalid."""


class CapabilitySecretUnavailableError(CapabilityError):
    """Raised when a capability has no decryptable API Key."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeatherConfiguration(StrictModel):
    api_host: AnyHttpUrl
    timeout_seconds: float = Field(gt=0, le=60)


class TimeConfiguration(StrictModel):
    pass


class WebSearchConfiguration(StrictModel):
    api_host: AnyHttpUrl
    timeout_seconds: float = Field(gt=0, le=60)
    max_results: int = Field(ge=1, le=20)


type CapabilityConfiguration = WeatherConfiguration | TimeConfiguration | WebSearchConfiguration


class CapabilityUpdate(StrictModel):
    enabled: bool
    configuration: dict[str, JsonValue]
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)
    clear_api_key: bool = False

    @model_validator(mode="after")
    def validate_secret_action(self) -> "CapabilityUpdate":
        if self.api_key is not None and self.clear_api_key:
            raise ValueError("api_key and clear_api_key are mutually exclusive")
        return self


@dataclass(frozen=True)
class CapabilitySeed:
    key: CapabilityKey
    enabled: bool
    configuration: dict[str, JsonValue]
    api_key: str | None


@dataclass(frozen=True)
class StoredCapability:
    key: CapabilityKey
    enabled: bool
    configuration: dict[str, JsonValue]
    encrypted_api_key: str | None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CapabilityState:
    key: CapabilityKey
    enabled: bool
    configuration: CapabilityConfiguration
    api_key: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class CapabilityView:
    key: CapabilityKey
    enabled: bool
    configuration: dict[str, JsonValue]
    api_key_masked: str | None
    can_reveal_api_key: bool
    updated_at: datetime | None
