import subprocess
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from somai_chat.core.config import Settings, get_settings


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


@pytest.mark.parametrize("api_key", ["", "   "])
def test_settings_reject_empty_or_blank_api_key(api_key: str) -> None:
    with pytest.raises(ValidationError):
        Settings(openai_api_key=api_key, openai_model="chat-model")


@pytest.mark.parametrize("model", ["", "   "])
def test_settings_reject_empty_or_blank_model(model: str) -> None:
    with pytest.raises(ValidationError):
        Settings(openai_api_key="secret", openai_model=model)


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


def test_dev_target_explains_missing_api_entry_point(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["make", "-f", str(project_root / "Makefile"), "dev"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "API entry point is not implemented yet; complete Task 5" in result.stdout + result.stderr
