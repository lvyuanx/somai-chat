from pathlib import Path


def test_admin_console_hidden_attribute_overrides_grid_layout() -> None:
    stylesheet = (
        Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "admin_web" / "admin.css"
    ).read_text(encoding="utf-8")

    assert "#console[hidden]{display:none}" in stylesheet


def test_login_uses_one_reusable_error_message() -> None:
    admin_web = Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "admin_web"
    html = (admin_web / "index.html").read_text(encoding="utf-8")
    script = (admin_web / "admin.js").read_text(encoding="utf-8")

    assert 'id="login-error"' in html
    assert "loginError.textContent = error.message" in script
    assert "login.insertAdjacentHTML" not in script


def test_chat_workspace_stays_inside_the_admin_shell() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "admin_web" / "admin.js"
    ).read_text(encoding="utf-8")

    assert "showChatWorkspace" in script
    assert "window.location.assign('/assets/index.html')" not in script
    assert 'src="/assets/index.html?embed=1"' in script


def test_embedded_chat_uses_the_admin_color_mode() -> None:
    web_directory = Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "web"

    assert "body.embedded" in (web_directory / "embed.css").read_text(encoding="utf-8")
    assert "document.body.classList.add(\"embedded\")" in (web_directory / "app.js").read_text(encoding="utf-8")
