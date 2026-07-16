import re
from functools import lru_cache
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _normalize_host(value: str) -> str:
    if "%" in value:
        raise ValueError("Origin contains an invalid host")
    try:
        return ip_address(value).compressed.lower()
    except ValueError:
        if re.fullmatch(r"[0-9.]+", value):
            raise ValueError("Origin contains an invalid IP address") from None
    try:
        ascii_host = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise ValueError("Origin contains an invalid host") from None
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or any(_HOST_LABEL.fullmatch(label) is None for label in labels):
        raise ValueError("Origin contains an invalid host")
    return ascii_host


def normalize_origin(value: str) -> str:
    """Validate and canonicalize an HTTP Origin value."""

    if value != value.strip():
        raise ValueError("Origin must not contain surrounding whitespace")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("Origin must use HTTP or HTTPS and include a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Origin must not contain user information")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Origin must not contain a path, query, or fragment")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Origin contains an invalid port") from error
    if parsed.netloc.endswith(":"):
        raise ValueError("Origin contains an empty port")
    host = _normalize_host(parsed.hostname)
    if ":" in host:
        host = f"[{host}]"
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    port_suffix = "" if port is None or port == default_port else f":{port}"
    return f"{parsed.scheme.lower()}://{host}{port_suffix}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOMAI_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    host: str = Field(default="0.0.0.0", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    openai_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    openai_api_key: SecretStr
    openai_model: str = Field(min_length=1)
    model_temperature: float = Field(default=0.4, ge=0, le=2)
    model_max_tokens: int = Field(default=800, gt=0)
    model_timeout_seconds: float = Field(default=30, gt=0)
    max_message_length: int = Field(default=8000, gt=0)
    max_websocket_message_bytes: int = Field(default=32768, gt=0)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"])

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_openai_api_key(cls, value: object) -> object:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                raise ValueError("OpenAI API key must not be empty")
        return secret

    @field_validator("openai_model", mode="before")
    @classmethod
    def validate_openai_model(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("OpenAI model must not be empty")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def normalize_allowed_origins(cls, values: list[str]) -> list[str]:
        return [normalize_origin(value) for value in values]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
