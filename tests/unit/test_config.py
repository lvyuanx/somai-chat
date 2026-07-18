import subprocess
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from somai_chat.core.config import Settings, get_settings, normalize_origin


def test_settings_accept_openai_compatible_provider() -> None:
    settings = Settings(
        openai_base_url="https://model.example/v1",
        openai_api_key=SecretStr("secret"),
        openai_model="chat-model",
    )

    assert str(settings.openai_base_url).rstrip("/") == "https://model.example/v1"
    assert settings.openai_api_key.get_secret_value() == "secret"
    assert settings.openai_model == "chat-model"


def test_settings_configures_database_and_administrator_credentials() -> None:
    settings = Settings(
        openai_api_key="chat-secret",
        openai_model="chat-model",
        database_url="mysql+asyncmy://somai:pass@db:3306/somai",
        admin_session_secret="session-secret",
        client_key_pepper="pepper-value",
    )

    assert settings.database_url == "mysql+asyncmy://somai:pass@db:3306/somai"
    assert settings.admin_username == "admin"
    assert settings.admin_password.get_secret_value() == "123456"
    assert settings.admin_session_secret.get_secret_value() == "session-secret"
    assert settings.client_key_pepper.get_secret_value() == "pepper-value"


def test_settings_hides_administrator_secrets_in_repr() -> None:
    settings = Settings(
        openai_api_key="chat-secret",
        openai_model="chat-model",
        database_url="mysql+asyncmy://somai:pass@db:3306/somai",
        admin_password="admin-password",
        admin_session_secret="session-secret",
        client_key_pepper="pepper-value",
    )

    assert "admin-password" not in repr(settings)
    assert "session-secret" not in repr(settings)
    assert "pepper-value" not in repr(settings)


def test_production_rejects_default_administrator_password() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            openai_api_key="chat-secret",
            openai_model="chat-model",
            database_url="mysql+asyncmy://somai:pass@db:3306/somai",
            admin_session_secret="production-session-secret",
            client_key_pepper="production-pepper",
        )


@pytest.mark.parametrize("placeholder", ["replace-me", "change-me", "your-secret-here"])
def test_production_rejects_placeholder_administrator_secrets(placeholder: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            openai_api_key="chat-secret",
            openai_model="chat-model",
            database_url="mysql+asyncmy://somai:pass@db:3306/somai",
            admin_password="strong-password",
            admin_session_secret=placeholder,
            client_key_pepper="production-pepper",
        )


def test_settings_accepts_optional_qwen_vision_provider() -> None:
    settings = Settings(
        openai_api_key="chat-secret",
        openai_model="chat-model",
        vision_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        vision_api_key="vision-secret",
        vision_model="qwen3-vl-plus",
    )

    assert str(settings.vision_base_url).rstrip("/") == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.vision_api_key is not None
    assert settings.vision_api_key.get_secret_value() == "vision-secret"
    assert settings.vision_model == "qwen3-vl-plus"
    assert settings.max_image_urls == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"vision_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        {"vision_api_key": "vision-secret"},
        {"vision_model": "qwen3-vl-plus"},
        {"max_image_urls": 0},
    ],
)
def test_settings_rejects_incomplete_or_invalid_vision_configuration(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(openai_api_key="chat-secret", openai_model="chat-model", **overrides)


def test_settings_reject_non_positive_message_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key=SecretStr("secret"),
            openai_model="chat-model",
            max_message_length=0,
        )


def test_settings_reject_non_positive_websocket_byte_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key=SecretStr("secret"),
            openai_model="chat-model",
            max_websocket_message_bytes=0,
        )


def test_settings_defaults_websocket_byte_limit() -> None:
    settings = Settings(openai_api_key="secret", openai_model="chat-model")

    assert settings.max_websocket_message_bytes == 32768
    assert settings.websocket_transport_max_bytes == 1048576


def test_settings_rejects_transport_limit_below_application_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key="secret",
            openai_model="chat-model",
            max_websocket_message_bytes=1024,
            websocket_transport_max_bytes=128,
        )


def test_settings_default_server_bind() -> None:
    settings = Settings(openai_api_key="secret", openai_model="chat-model")

    assert settings.host == "0.0.0.0"
    assert settings.port == 8000


@pytest.mark.parametrize("port", [0, 65536])
def test_settings_reject_out_of_range_server_port(port: int) -> None:
    with pytest.raises(ValidationError):
        Settings(openai_api_key="secret", openai_model="chat-model", port=port)


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("HTTP://Example.COM:80", "http://example.com"),
        ("https://LOCALHOST:443", "https://localhost"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("https://[::1]:8443", "https://[::1]:8443"),
    ],
)
def test_normalize_origin_canonicalizes_standard_origins(origin: str, expected: str) -> None:
    assert normalize_origin(origin) == expected


@pytest.mark.parametrize(
    "origin",
    [
        "ftp://example.com",
        "https://example.com/path",
        "https://example.com?query=yes",
        "https://example.com#fragment",
        "https://user@example.com",
        "https://example.com:invalid",
        "https://example.com:",
        "https://example.com ",
        "https://exa mple.com",
        "https://-example.com",
        "https://example..com",
        "http://999.999.999.999",
        "https://",
    ],
)
def test_normalize_origin_rejects_non_origin_values(origin: str) -> None:
    with pytest.raises(ValueError):
        normalize_origin(origin)


def test_settings_normalizes_allowed_origins() -> None:
    settings = Settings(
        openai_api_key="secret",
        openai_model="chat-model",
        allowed_origins=["HTTP://Example.COM:80", "https://LOCALHOST:443"],
    )

    assert settings.allowed_origins == ["http://example.com", "https://localhost"]


def test_settings_hide_api_key_in_repr() -> None:
    settings = Settings(openai_api_key=SecretStr("top-secret"), openai_model="chat-model")

    assert "top-secret" not in repr(settings)


@pytest.mark.parametrize("api_key", ["", "   "])
def test_settings_reject_empty_or_blank_api_key(api_key: str) -> None:
    with pytest.raises(ValidationError):
        Settings(openai_api_key=api_key, openai_model="chat-model")


@pytest.mark.parametrize("model", ["", "   "])
def test_settings_reject_empty_or_blank_model(model: str) -> None:
    with pytest.raises(ValidationError):
        Settings(openai_api_key="secret", openai_model=model)


def test_settings_configures_qweather_weather_service() -> None:
    settings = Settings(
        openai_api_key=SecretStr("test-key"),
        openai_model="test-model",
        qweather_api_host="https://example.qweatherapi.com",
        qweather_api_key=SecretStr("weather-key"),
    )

    assert str(settings.qweather_api_host) == "https://example.qweatherapi.com/"
    assert settings.qweather_api_key.get_secret_value() == "weather-key"


def test_get_settings_loads_prefixed_environment_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("SOMAI_OPENAI_API_KEY", "environment-secret")
    monkeypatch.setenv("SOMAI_OPENAI_MODEL", "environment-model")
    monkeypatch.setenv("SOMAI_OPENAI_BASE_URL", "https://environment.example/v1")

    try:
        settings = get_settings()

        assert isinstance(settings.openai_api_key, SecretStr)
        assert settings.openai_api_key.get_secret_value() == "environment-secret"
        assert settings.openai_model == "environment-model"
        assert str(settings.openai_base_url).rstrip("/") == "https://environment.example/v1"
        assert get_settings() is settings
    finally:
        get_settings.cache_clear()


def test_settings_load_from_dotenv_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOMAI_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SOMAI_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("SOMAI_OPENAI_BASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOMAI_OPENAI_API_KEY=dotenv-secret\n"
        "SOMAI_OPENAI_MODEL=dotenv-model\n"
        "SOMAI_OPENAI_BASE_URL=https://dotenv.example/v1\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.openai_api_key.get_secret_value() == "dotenv-secret"
    assert settings.openai_model == "dotenv-model"
    assert str(settings.openai_base_url).rstrip("/") == "https://dotenv.example/v1"


def test_dev_target_uses_module_server_entrypoint() -> None:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["make", "-n", "dev"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    output = result.stdout + result.stderr
    assert "uv run python -m somai_chat.main" in output
    assert "uvicorn somai_chat.main:app" not in output
    assert "SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES" not in output
    assert "API entry point is not implemented yet" not in output


def test_example_environment_documents_websocket_size_limit() -> None:
    project_root = Path(__file__).resolve().parents[2]

    assert "SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES=32768" in (project_root / ".env.example").read_text()
    assert "SOMAI_WEBSOCKET_TRANSPORT_MAX_BYTES=1048576" in (project_root / ".env.example").read_text()
    assert "SOMAI_HOST=0.0.0.0" in (project_root / ".env.example").read_text()
    assert "SOMAI_PORT=8000" in (project_root / ".env.example").read_text()
