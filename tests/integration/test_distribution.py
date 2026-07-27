import json
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import pytest

from somai_chat.core.config import Settings

ROOT = Path(__file__).parents[2]


def test_container_runs_as_somai_through_application_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "USER somai" in dockerfile
    assert 'CMD ["python", "-m", "somai_chat.main"]' in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert (ROOT / "uv.lock").is_file()
    assert "ARG UV_VERSION=0.11.13" in dockerfile
    assert "COPY pyproject.toml uv.lock README.md ./" in dockerfile
    assert "uv sync --locked --no-dev" in dockerfile
    assert "replace-me" not in dockerfile


def test_container_healthcheck_uses_configured_runtime_port(monkeypatch: pytest.MonkeyPatch) -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    health_line = next(
        line.strip() for line in dockerfile.splitlines() if line.strip().startswith('CMD ["python", "-c"')
    )
    command = json.loads(health_line.removeprefix("CMD "))
    requested_urls: list[str] = []

    monkeypatch.setenv("SOMAI_PORT", "8123")
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: requested_urls.append(f"{url}|{timeout}"))
    exec(command[2], {})

    assert command[:2] == ["python", "-c"]
    assert requested_urls == ["http://127.0.0.1:8123/health/live|2"]


def test_readme_documents_settings_and_make_commands() -> None:
    readme = (ROOT / "README.md").read_text()
    settings_fields = Settings.model_fields

    for field_name in settings_fields:
        assert f"SOMAI_{field_name.upper()}" in readme
    for command in (
        "make install",
        "make dev",
        "make format",
        "make lint",
        "make typecheck",
        "make test",
        "make check",
    ):
        assert command in readme
    assert "uv sync --locked --extra dev" in (ROOT / "Makefile").read_text()
    assert "-e SOMAI_ENVIRONMENT=production" in readme


def test_distribution_contract_keeps_secrets_and_build_outputs_out() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    gitignore = (ROOT / ".gitignore").read_text().splitlines()

    assert ".env" in dockerignore
    assert "!.env.example" in dockerignore
    assert ".env" in gitignore
    assert "!.env.example" in gitignore
    assert {"dist/", "build/", ".venv/", "__pycache__/"} <= set(gitignore)


def test_built_wheel_contains_browser_console_assets(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("somai_chat-*.whl"))
    expected = {
        f"somai_chat/web/{asset}"
        for asset in (
            "index.html",
            "app.css",
            "workflow.css",
            "responsive.css",
            "app.js",
            "view.js",
            "workflow.js",
            "markdown.js",
        )
    }

    with zipfile.ZipFile(wheel) as archive:
        assert expected <= set(archive.namelist())
