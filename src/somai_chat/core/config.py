import re
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_PRODUCTION_PLACEHOLDER_MARKERS = ("replace", "change-me", "your-secret", "placeholder")


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
    database_user: str = Field(default="somai", min_length=1)
    database_password: SecretStr = SecretStr("change-me")
    database_host: str = Field(default="127.0.0.1", min_length=1)
    database_port: int = Field(default=3306, ge=1, le=65535)
    database_name: str = Field(default="somai", min_length=1)
    admin_username: str = Field(default="admin", min_length=1)
    admin_password: SecretStr = SecretStr("123456")
    admin_session_secret: SecretStr = SecretStr("change-me")
    client_key_pepper: SecretStr = SecretStr("change-me")
    client_key_encryption_secret: SecretStr = SecretStr("change-me")
    capability_secret_encryption_secret: SecretStr = SecretStr("change-me")
    model_temperature: float = Field(default=0.4, ge=0, le=2)
    model_max_tokens: int = Field(default=800, gt=0)
    model_timeout_seconds: float = Field(default=30, gt=0)
    vision_base_url: AnyHttpUrl | None = None
    vision_api_key: SecretStr | None = None
    vision_model: str | None = None
    vision_timeout_seconds: float = Field(default=30, gt=0)
    media_root: Path = Field(default_factory=lambda: Path.cwd() / "media")
    max_image_urls: int = Field(default=4, ge=1, le=4)
    max_image_download_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    qweather_api_host: AnyHttpUrl | None = None
    qweather_api_key: SecretStr | None = None
    weather_timeout_seconds: float = Field(default=5, gt=0)
    tavily_api_host: AnyHttpUrl = AnyHttpUrl("https://api.tavily.com")
    tavily_api_key: SecretStr | None = None
    tavily_timeout_seconds: float = Field(default=10, gt=0)
    tavily_max_results: int = Field(default=5, ge=1, le=20)
    max_message_length: int = Field(default=8000, gt=0)
    max_websocket_message_bytes: int = Field(default=32768, gt=0)
    websocket_transport_max_bytes: int = Field(default=1048576, gt=0)
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

    @field_validator(
        "admin_password",
        "admin_session_secret",
        "client_key_pepper",
        "client_key_encryption_secret",
        "capability_secret_encryption_secret",
        mode="before",
    )
    @classmethod
    def validate_administrator_secret(cls, value: object) -> object:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                raise ValueError("Administrator secret must not be empty")
        return secret

    @field_validator("database_user", "database_host", "database_name", mode="before")
    @classmethod
    def validate_database_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Database setting must not be empty")
        return value

    @field_validator("database_password", mode="before")
    @classmethod
    def validate_database_password(cls, value: object) -> object:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                raise ValueError("Database password must not be empty")
        return secret

    @field_validator("qweather_api_key", mode="before")
    @classmethod
    def validate_qweather_api_key(cls, value: object) -> object:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                raise ValueError("QWeather API key must not be empty")
        return secret

    @field_validator("tavily_api_key", mode="before")
    @classmethod
    def validate_tavily_api_key(cls, value: object) -> object:
        if value is None:
            return None
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                raise ValueError("Tavily API key must not be empty")
        return secret

    @field_validator("openai_model", mode="before")
    @classmethod
    def validate_openai_model(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("OpenAI model must not be empty")
        return value

    @field_validator("vision_api_key", mode="before")
    @classmethod
    def validate_vision_api_key(cls, value: object) -> object:
        if value is None:
            return None
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(secret, str):
            secret = secret.strip()
            if not secret:
                raise ValueError("Vision API key must not be empty")
        return secret

    @field_validator("vision_model", mode="before")
    @classmethod
    def validate_vision_model(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Vision model must not be empty")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def normalize_allowed_origins(cls, values: list[str]) -> list[str]:
        return [normalize_origin(value) for value in values]

    @model_validator(mode="after")
    def validate_websocket_limits(self) -> "Settings":
        if self.websocket_transport_max_bytes < self.max_websocket_message_bytes:
            raise ValueError("WebSocket transport limit must be at least the application limit")
        vision_configuration = (self.vision_base_url, self.vision_api_key, self.vision_model)
        vision_configured = any(value is not None for value in vision_configuration)
        vision_incomplete = any(value is None for value in vision_configuration)
        if vision_configured and vision_incomplete:
            raise ValueError("Vision endpoint, API key, and model must be configured together")
        if self.environment == "production":
            administrator_secrets = (
                self.admin_password.get_secret_value(),
                self.admin_session_secret.get_secret_value(),
                self.client_key_pepper.get_secret_value(),
                self.client_key_encryption_secret.get_secret_value(),
                self.capability_secret_encryption_secret.get_secret_value(),
            )
            if self.admin_password.get_secret_value() == "123456":
                raise ValueError("Production administrator password must not use the default value")
            if any(_is_placeholder_secret(secret) for secret in administrator_secrets):
                raise ValueError("Production administrator secrets must not use placeholder values")
            if _is_placeholder_secret(self.database_password.get_secret_value()):
                raise ValueError("Production database password must not use a placeholder value")
        return self

    def database_connection_url(self) -> str:
        """Build the async MySQL URL without exposing the password in Settings repr."""

        return URL.create(
            "mysql+asyncmy",
            username=self.database_user,
            password=self.database_password.get_secret_value(),
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        ).render_as_string(hide_password=False)


def _is_placeholder_secret(value: str) -> bool:
    normalized = value.strip().lower()
    return any(marker in normalized for marker in _PRODUCTION_PLACEHOLDER_MARKERS)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
