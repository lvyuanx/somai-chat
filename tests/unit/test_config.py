import pytest
from pydantic import SecretStr, ValidationError

from somai_chat.core.config import Settings


def test_settings_accept_openai_compatible_provider() -> None:
    settings = Settings(
        openai_base_url="https://model.example/v1",
        openai_api_key=SecretStr("secret"),
        openai_model="chat-model",
    )

    assert str(settings.openai_base_url).rstrip("/") == "https://model.example/v1"
    assert settings.openai_api_key.get_secret_value() == "secret"
    assert settings.openai_model == "chat-model"


def test_settings_reject_non_positive_message_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key=SecretStr("secret"),
            openai_model="chat-model",
            max_message_length=0,
        )


def test_settings_hide_api_key_in_repr() -> None:
    settings = Settings(openai_api_key=SecretStr("top-secret"), openai_model="chat-model")

    assert "top-secret" not in repr(settings)
