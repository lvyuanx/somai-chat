from datetime import date
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from somai_chat import main as main_module
from somai_chat.application.conversation import ConversationRuntime
from somai_chat.core.config import Settings


def test_application_uses_generated_database_connection_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class Closeable:
        async def close(self) -> None:
            return None

    def create_sessions(url: str) -> tuple[Closeable, object]:
        captured["url"] = url
        return Closeable(), object()

    settings = Settings(
        _env_file=None,
        openai_api_key="secret",
        openai_model="model",
        database_user="robot",
        database_password="p@ssword",
        database_host="db",
        database_name="chat",
    )
    monkeypatch.setattr(main_module, "create_session_factory", create_sessions)

    with TestClient(main_module.create_app(settings=settings, runtime=cast(ConversationRuntime, object()))):
        pass

    url = make_url(captured["url"])
    assert (url.username, url.password, url.host, url.database) == ("robot", "p@ssword", "db", "chat")


def test_application_passes_log_dir_to_logging_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Closeable:
        async def close(self) -> None:
            return None

    def create_sessions(url: str) -> tuple[Closeable, object]:
        del url
        return Closeable(), object()

    def fake_configure_logging(level: str, *, log_dir: Path | None = None, stream: object | None = None) -> None:
        captured["level"] = level
        captured["log_dir"] = log_dir
        captured["stream"] = stream

    settings = Settings(
        _env_file=None,
        openai_api_key="secret",
        openai_model="model",
        log_dir=tmp_path / "runtime-logs",
    )
    monkeypatch.setattr(main_module, "create_session_factory", create_sessions)
    monkeypatch.setattr(main_module, "configure_logging", fake_configure_logging)

    with TestClient(main_module.create_app(settings=settings, runtime=cast(ConversationRuntime, object()))):
        pass

    assert captured == {"level": "INFO", "log_dir": tmp_path / "runtime-logs", "stream": None}


def test_application_lifespan_emits_project_startup_and_shutdown_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Closeable:
        async def close(self) -> None:
            return None

    def create_sessions(url: str) -> tuple[Closeable, object]:
        del url
        return Closeable(), object()

    settings = Settings(
        _env_file=None,
        openai_api_key="secret",
        openai_model="model",
        log_dir=tmp_path / "logs",
    )
    monkeypatch.setattr(main_module, "create_session_factory", create_sessions)

    with TestClient(main_module.create_app(settings=settings, runtime=cast(ConversationRuntime, object()))):
        pass

    project_log = tmp_path / "logs" / f"{date.today().isoformat()}-project.log"
    log_text = project_log.read_text(encoding="utf-8")
    assert "应用启动开始" in log_text
    assert "应用启动完成" in log_text
    assert "应用关闭完成" in log_text
    assert "secret" not in log_text


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
        "SOMAI_DATABASE_USER=somai\n"
        "SOMAI_DATABASE_PASSWORD=pass\n"
        "SOMAI_DATABASE_HOST=db\n"
        "SOMAI_DATABASE_PORT=3306\n"
        "SOMAI_DATABASE_NAME=somai\n"
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
        "SOMAI_DATABASE_USER",
        "SOMAI_DATABASE_PASSWORD",
        "SOMAI_DATABASE_HOST",
        "SOMAI_DATABASE_PORT",
        "SOMAI_DATABASE_NAME",
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
        "log_level": "error",
        "port": 9123,
        "reload": False,
        "ws_max_size": 34567,
    }
