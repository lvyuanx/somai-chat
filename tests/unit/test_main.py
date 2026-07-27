from pathlib import Path
from typing import Any

import pytest

from somai_chat import main as main_module
from somai_chat.core.config import Settings


def test_application_registers_capability_admin_routes() -> None:
    paths = set(main_module.create_app().openapi()["paths"])

    assert "/api/v1/admin/capabilities" in paths
    assert "/api/v1/admin/capabilities/{capability}" in paths
    assert "/api/v1/admin/capabilities/{capability}/api-key/reveal" in paths


def test_capability_seeds_preserve_existing_environment_behavior() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="test-secret",
        openai_model="test-model",
        qweather_api_host="https://example.qweatherapi.com",
        qweather_api_key="weather-key",
        tavily_api_key="tavily-key",
    )
    seeds = {seed.key: seed for seed in main_module._capability_seeds(settings)}

    assert seeds["weather"].enabled is True
    assert seeds["weather"].api_key == "weather-key"
    assert seeds["time"].enabled is True
    assert seeds["web_search"].enabled is True
    assert seeds["web_search"].api_key == "tavily-key"


def test_run_loads_dotenv_and_passes_server_settings_to_uvicorn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "SOMAI_ENVIRONMENT=production\n"
        "SOMAI_OPENAI_API_KEY=test-secret\n"
        "SOMAI_OPENAI_MODEL=test-model\n"
        "SOMAI_DATABASE_URL=mysql+asyncmy://somai:pass@db:3306/somai\n"
        "SOMAI_ADMIN_PASSWORD=production-password\n"
        "SOMAI_ADMIN_SESSION_SECRET=production-session-secret\n"
        "SOMAI_CLIENT_KEY_PEPPER=production-pepper\n"
        "SOMAI_CLIENT_KEY_ENCRYPTION_SECRET=production-encryption-secret\n"
        "SOMAI_CAPABILITY_SECRET_ENCRYPTION_SECRET=production-capability-encryption-secret\n"
        "SOMAI_HOST=127.0.0.1\n"
        "SOMAI_PORT=9123\n"
        "SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES=23456\n"
        "SOMAI_WEBSOCKET_TRANSPORT_MAX_BYTES=34567\n",
        encoding="utf-8",
    )
    for name in (
        "SOMAI_ENVIRONMENT",
        "SOMAI_OPENAI_API_KEY",
        "SOMAI_OPENAI_MODEL",
        "SOMAI_DATABASE_URL",
        "SOMAI_ADMIN_PASSWORD",
        "SOMAI_ADMIN_SESSION_SECRET",
        "SOMAI_CLIENT_KEY_PEPPER",
        "SOMAI_CLIENT_KEY_ENCRYPTION_SECRET",
        "SOMAI_CAPABILITY_SECRET_ENCRYPTION_SECRET",
        "SOMAI_HOST",
        "SOMAI_PORT",
        "SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES",
        "SOMAI_WEBSOCKET_TRANSPORT_MAX_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    captured: dict[str, Any] = {}

    def fake_run(app: str, **kwargs: Any) -> None:
        captured["app"] = app
        captured.update(kwargs)

    main_module.get_settings.cache_clear()
    try:
        monkeypatch.setattr(main_module.uvicorn, "run", fake_run)
        main_module.run()
    finally:
        main_module.get_settings.cache_clear()

    assert captured == {
        "app": "somai_chat.main:app",
        "host": "127.0.0.1",
        "port": 9123,
        "reload": False,
        "ws_max_size": 34567,
    }
