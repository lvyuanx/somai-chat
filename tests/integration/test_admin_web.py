from pathlib import Path


def test_admin_console_hidden_attribute_overrides_grid_layout() -> None:
    stylesheet = (
        Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "admin_web" / "admin.css"
    ).read_text(encoding="utf-8")

    assert "#console[hidden]{display:none}" in stylesheet
