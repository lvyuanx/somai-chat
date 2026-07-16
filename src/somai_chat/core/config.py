from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOMAI_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    openai_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    openai_api_key: SecretStr
    openai_model: str = Field(min_length=1)
    model_temperature: float = Field(default=0.4, ge=0, le=2)
    model_max_tokens: int = Field(default=800, gt=0)
    model_timeout_seconds: float = Field(default=30, gt=0)
    max_message_length: int = Field(default=8000, gt=0)
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"])


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
