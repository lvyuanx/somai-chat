from pathlib import Path

from somai_chat.core.config import Settings

ROOT = Path(__file__).parents[2]


def test_container_runs_as_somai_through_application_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "USER somai" in dockerfile
    assert 'CMD ["python", "-m", "somai_chat.main"]' in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "replace-me" not in dockerfile


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


def test_distribution_contract_keeps_secrets_and_build_outputs_out() -> None:
    dockerignore = (ROOT / ".dockerignore").read_text().splitlines()
    gitignore = (ROOT / ".gitignore").read_text().splitlines()

    assert ".env" in dockerignore
    assert "!.env.example" in dockerignore
    assert ".env" in gitignore
    assert "!.env.example" in gitignore
    assert {"dist/", "build/", ".venv/", "__pycache__/"} <= set(gitignore)


def test_python_package_contains_browser_console_assets() -> None:
    web = ROOT / "src" / "somai_chat" / "web"

    for asset in ("index.html", "app.css", "responsive.css", "app.js", "view.js", "markdown.js"):
        assert (web / asset).is_file()
