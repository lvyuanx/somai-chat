from pathlib import Path


def test_alembic_uses_shared_split_database_settings() -> None:
    source = (Path(__file__).resolve().parents[2] / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "get_settings" in source
    assert "database_connection_url()" in source
    assert 'os.environ.get("SOMAI_DATABASE_URL")' not in source
    assert 'replace("%", "%%")' in source
