import pytest
from langchain_openai.chat_models import _client_utils
from pydantic import SecretStr

from somai_chat.core.config import Settings
from somai_chat.providers.llm import create_chat_model


@pytest.fixture(autouse=True)
def clear_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    _client_utils._cached_sync_httpx_client.cache_clear()
    _client_utils._cached_async_httpx_client.cache_clear()


def test_create_chat_model_maps_openai_compatible_settings() -> None:
    settings = Settings(
        openai_api_key=SecretStr("provider-secret"),
        openai_base_url="https://models.example.test/v1",
        openai_model="example-chat",
        model_temperature=0.25,
        model_max_tokens=321,
        model_timeout_seconds=12.5,
    )

    model = create_chat_model(settings)

    assert model.openai_api_base == str(settings.openai_base_url)
    assert model.openai_api_key == settings.openai_api_key
    assert model.model_name == "example-chat"
    assert model.temperature == 0.25
    assert model.max_tokens == 321
    assert model.request_timeout == 12.5
    assert model.streaming is True


def test_create_chat_model_does_not_expose_api_key_in_repr() -> None:
    secret = "do-not-leak-this-key"
    model = create_chat_model(Settings(openai_api_key=SecretStr(secret), openai_model="example-chat"))

    assert secret not in repr(model)
    assert secret not in str(model)
