from pathlib import Path


def test_admin_console_hidden_attribute_overrides_grid_layout() -> None:
    stylesheet = (Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "admin_web" / "admin.css").read_text(
        encoding="utf-8"
    )

    assert "#console[hidden]{display:none}" in stylesheet


def test_login_uses_one_reusable_error_message() -> None:
    admin_web = Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src"
    script = (admin_web / "App.vue").read_text(encoding="utf-8")

    assert "loginError" in script
    assert "loginError.value = error.message" in script
    assert "ElementPlus" not in script


def test_chat_workspace_stays_inside_the_admin_shell() -> None:
    script = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(
        encoding="utf-8"
    )

    assert "chat-page" in script
    assert "window.location.assign('/assets/index.html')" not in script
    assert 'src="/assets/index.html?embed=1"' in script


def test_embedded_chat_uses_the_admin_color_mode() -> None:
    web_directory = Path(__file__).resolve().parents[2] / "src" / "somai_chat" / "web"

    assert "body.embedded" in (web_directory / "embed.css").read_text(encoding="utf-8")
    assert 'document.body.classList.add("embedded")' in (web_directory / "app.js").read_text(encoding="utf-8")


def test_admin_build_uses_element_plus() -> None:
    package = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "package.json").read_text(encoding="utf-8")

    assert '"element-plus"' in package


def test_admin_menu_selects_the_internal_view() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert '@select="active = $event"' in app


def test_admin_has_capability_management_cards() -> None:
    directory = Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src"
    app = (directory / "App.vue").read_text(encoding="utf-8")
    capability = (directory / "CapabilityManagement.vue").read_text(encoding="utf-8")

    assert 'index="capabilities"' in app
    assert "<CapabilityManagement" in app
    assert all(label in capability for label in ("查询天气", "查询时间", "联网搜索", "保存配置"))
    assert "/capabilities" in capability


def test_revealed_capability_key_uses_the_existing_input() -> None:
    capability = (
        Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "CapabilityManagement.vue"
    ).read_text(encoding="utf-8")

    assert ':model-value="capabilityKeyInputValue(draft)"' in capability
    assert ":type=\"draft.revealed_api_key ? 'text' : 'password'\"" in capability
    assert '@input="updateCapabilityKeyInput(draft, $event)"' in capability
    assert "revealed-secret" not in capability


def test_capability_key_clear_button_clears_the_current_draft_only() -> None:
    capability = (
        Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "CapabilityManagement.vue"
    ).read_text(encoding="utf-8")

    assert 'v-if="draft.can_reveal_api_key"' in capability
    assert "clearCapabilityKeyInput(draft)" in capability
    assert ':icon="Delete"' in capability
    assert '@keydown.delete="handleCapabilityKeydown(draft, $event)"' in capability
    assert "clear_api_key" in capability


def test_admin_vue_components_stay_within_size_limit() -> None:
    directory = Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src"
    for component in directory.glob("*.vue"):
        assert len(component.read_text(encoding="utf-8").splitlines()) <= 500


def test_client_management_uses_online_presence_cards() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "client-grid" in app
    assert "client.online" in app
    assert "在线" in app
    assert "el-table" not in app


def test_client_enabled_state_uses_a_switch_control() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "<el-switch" in app
    assert '@change="toggleClient(client)"' in app
    assert 'active-text="已启用"' in app
    assert 'inactive-text="已停用"' in app


def test_client_key_is_masked_until_an_administrator_reveals_it() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "client.key_masked" in app
    assert "revealKey(client)" in app
    assert "/key/reveal" in app
    assert "copyKey(client)" in app


def test_admin_request_handles_non_json_error_responses() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "await response.json().catch(() => null)" in app


def test_create_client_shows_the_server_error_in_its_dialog() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "clientFormError" in app
    assert "clientFormError.value = error.message" in app
    assert 'v-if="clientFormError"' in app


def test_create_dialog_does_not_render_template_delimiters_as_text() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "show-icon />\n        ><el-form-item" not in app


def test_legacy_key_hint_does_not_compete_with_the_masked_key_row() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert "client-key-legacy" in app
    assert '<el-tag v-else type="warning" effect="plain">需轮换</el-tag>' not in app


def test_key_visibility_icon_reflects_its_current_state() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert ':icon="revealedKeys[client.id] ? View : Hide"' in app


def test_copying_a_revealed_key_confirms_success() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert 'ElMessage.success("Key 已复制")' in app


def test_copying_a_hidden_key_does_not_require_revealing_it() -> None:
    app = (Path(__file__).resolve().parents[2] / "frontend" / "admin" / "src" / "App.vue").read_text(encoding="utf-8")

    assert 'await request(`/clients/${client.id}/key/reveal`, { method: "POST" })' in app
    assert ':disabled="!revealedKeys[client.id]"' not in app


def test_embedded_chat_allows_only_same_origin_framing() -> None:
    from fastapi.testclient import TestClient

    from somai_chat.main import create_app

    with TestClient(create_app()) as client:
        embedded = client.get("/assets/index.html?embed=1")
        standalone = client.get("/assets/index.html")

    assert "frame-ancestors 'self'" in embedded.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in standalone.headers["content-security-policy"]
