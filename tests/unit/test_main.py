from pathlib import Path
from typing import Any

import pytest

from somai_chat import main as main_module


def test_run_loads_dotenv_and_passes_server_settings_to_uvicorn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".env").write_text(
        "SOMAI_ENVIRONMENT=production\n"
        "SOMAI_OPENAI_API_KEY=test-secret\n"
        "SOMAI_OPENAI_MODEL=test-model\n"
        "SOMAI_HOST=127.0.0.1\n"
        "SOMAI_PORT=9123\n"
        "SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES=23456\n",
        encoding="utf-8",
    )
    for name in (
        "SOMAI_ENVIRONMENT",
        "SOMAI_OPENAI_API_KEY",
        "SOMAI_OPENAI_MODEL",
        "SOMAI_HOST",
        "SOMAI_PORT",
        "SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES",
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
        "ws_max_size": 23456,
    }
