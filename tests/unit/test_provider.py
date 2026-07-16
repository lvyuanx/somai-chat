import httpx
import openai
import pytest
from langchain_openai.chat_models import _client_utils
from pydantic import SecretStr

from somai_chat.core.config import Settings
from somai_chat.providers.llm import create_chat_model, is_model_provider_unavailable


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


def test_official_openai_endpoint_requests_stream_usage() -> None:
    model = create_chat_model(
        Settings(
            openai_api_key=SecretStr("provider-secret"),
            openai_base_url="https://api.openai.com/v1",
            openai_model="example-chat",
        )
    )

    assert model.stream_usage is True


def test_custom_compatible_endpoint_does_not_request_stream_usage() -> None:
    model = create_chat_model(
        Settings(
            openai_api_key=SecretStr("provider-secret"),
            openai_base_url="https://models.example.test/v1",
            openai_model="example-chat",
        )
    )

    assert model.stream_usage is False


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(
            message="connection failed",
            request=httpx.Request("POST", "https://provider.example/v1"),
        ),
        openai.APITimeoutError(request=httpx.Request("POST", "https://provider.example/v1")),
        httpx.ConnectError("connection failed"),
        httpx.ReadTimeout("timed out"),
    ],
)
def test_model_provider_unavailable_classifier_recognizes_provider_errors(error: BaseException) -> None:
    assert is_model_provider_unavailable(error) is True


def test_model_provider_unavailable_classifier_rejects_unknown_errors() -> None:
    assert is_model_provider_unavailable(RuntimeError("graph bug")) is False


@pytest.mark.parametrize(
    "proxy_environment",
    [
        {"NO_PROXY": "models.example.test"},
        {
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "models.example.test",
        },
    ],
)
def test_create_chat_model_accepts_supported_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
    proxy_environment: dict[str, str],
) -> None:
    secret = "proxy-matrix-secret"
    for name, value in proxy_environment.items():
        monkeypatch.setenv(name, value)
    _client_utils._cached_sync_httpx_client.cache_clear()
    _client_utils._cached_async_httpx_client.cache_clear()

    model = create_chat_model(
        Settings(
            openai_api_key=SecretStr(secret),
            openai_base_url="https://models.example.test/v1",
            openai_model="example-chat",
        )
    )

    assert model.model_name == "example-chat"
    assert secret not in repr(model)
