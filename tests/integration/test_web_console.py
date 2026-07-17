from __future__ import annotations

import re
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from somai_chat.main import create_app


def test_debug_console_is_served_without_runtime_configuration() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SOMAI" in response.text


def test_debug_console_has_accessible_local_structure() -> None:
    with TestClient(create_app()) as client:
        html = client.get("/").text

    required_fragments = (
        'name="viewport"',
        'name="theme-color"',
        'id="connection-status"',
        'id="conversation-id"',
        'id="model-name"',
        'id="new-session"',
        'id="clear-display"',
        'id="message-timeline"',
        'id="live-status"',
        'aria-live="polite"',
        'for="message-input"',
        'id="message-input"',
        'id="send-stop"',
        'id="event-trace"',
        '<script type="module" src="/assets/app.js"></script>',
        'href="/assets/app.css"',
        'href="/assets/responsive.css"',
    )
    assert all(fragment in html for fragment in required_fragments)
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE)
    assert not re.search(r"(?:src|href)=[\"']https?://", html, re.IGNORECASE)
    assert html.count('aria-live="polite"') == 1
    timeline = re.search(r'<div id="message-timeline"[^>]*>', html)
    assert timeline is not None and "aria-live" not in timeline.group(0)
    assert "maxlength=" not in html


def test_debug_console_assets_are_served_with_expected_content_types() -> None:
    with TestClient(create_app()) as client:
        stylesheet = client.get("/assets/app.css")
        responsive = client.get("/assets/responsive.css")
        script = client.get("/assets/app.js")
        markdown = client.get("/assets/markdown.js")
        view = client.get("/assets/view.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert responsive.status_code == 200
    assert responsive.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert markdown.status_code == 200
    assert "javascript" in markdown.headers["content-type"]
    assert view.status_code == 200
    assert "javascript" in view.headers["content-type"]


def test_console_responses_have_security_and_no_cache_headers() -> None:
    expected_csp = (
        "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' ws: wss:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    with TestClient(create_app()) as client:
        paths = (
            "/",
            "/assets/app.css",
            "/assets/responsive.css",
            "/assets/app.js",
            "/assets/markdown.js",
            "/assets/view.js",
        )
        responses = [client.get(path) for path in paths]

    for response in responses:
        csp = response.headers["content-security-policy"]
        assert csp == expected_csp.replace("ws: wss:", "ws://testserver wss://testserver")
        assert " ws: " not in csp and " wss: " not in csp
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-cache"

    with TestClient(create_app()) as client:
        poisoned = client.get("/", headers={"host": "evil.example;script-src *"})

    poisoned_csp = poisoned.headers["content-security-policy"]
    assert "evil.example" not in poisoned_csp
    assert "script-src *" not in poisoned_csp
    assert "\r" not in poisoned_csp and "\n" not in poisoned_csp


def test_console_styles_cover_responsive_accessible_streaming_states() -> None:
    with TestClient(create_app()) as client:
        css = client.get("/assets/app.css").text
        responsive = client.get("/assets/responsive.css").text

    assert "@media" not in css
    assert "@media (max-width: 850px)" in responsive
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in responsive
    assert ".streaming-cursor" in css
    assert "--signal-orange" in css
    assert "--success-green" in css
    assert "--surface-base: #0d1523" in css
    assert "--surface-raised: #162238" in css
    assert "--accent-blue: #1f75fe" in css
    assert "border-radius: 14px" in css
    assert ".conversation-panel" in css
    assert "grid-template-rows: auto minmax(0, 1fr) auto" in css
    assert ".message-timeline" in css and "overflow-y: auto" in css
    assert "min-height: 0" in css
    assert ".visually-hidden" in css
    mobile = responsive[responsive.index("@media (max-width: 850px)") :]
    assert "grid-template-rows: auto minmax(0, 1fr)" in mobile
    assert re.search(r"height:\s*100vh;\s*height:\s*100dvh", mobile)
    assert "min-height: 0" in mobile
    assert ".session-rail" in mobile
    assert ".trace-rail" in mobile and "display: none" in mobile
    assert not re.search(r"\.side-rail\s*\{\s*display:\s*none", mobile)


def test_console_script_uses_safe_dom_and_websocket_state_machine() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text
        markdown = client.get("/assets/markdown.js").text
        view = client.get("/assets/view.js").text

    forbidden = ("innerHTML", "insertAdjacentHTML", "eval(", "new Function")
    required = (
        "localStorage",
        "WebSocket",
        "response.cancel",
        "message.create",
        "conversation.ready",
        "response.started",
        "response.delta",
        "response.completed",
        "response.cancelled",
        "textContent",
        "createElement",
        "reconnect",
    )
    assert not any(token in javascript or token in markdown or token in view for token in forbidden)
    assert all(token in javascript for token in required)
    assert 'import {markdownNodes} from "./markdown.js";' in view
    assert "export function markdownNodes" in markdown
    assert re.search(r'import \{[^}]*createConsoleView[^}]*\} from "\./view\.js";', javascript)
    assert "createConsoleView({" in javascript
    assert "export function createConsoleView" in view


def test_console_message_send_enters_pending_synchronously() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

    assert 'phase: "idle"' in javascript
    assert "pendingMessageId: null" in javascript
    assert "generating" not in javascript
    transition = re.compile(
        r"if \(sendEvent\(event, serialized\)\) \{\s*"
        r"state\.pendingMessageId = messageId;\s*"
        r"state\.requestStartedAt = Date\.now\(\);\s*"
        r'state\.phase = "pending";',
    )
    assert transition.search(javascript)


def test_console_submit_guards_pending_and_latches_cancelling() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

    pending_guard = re.compile(
        r'if \(state\.phase === "pending" \|\| state\.phase === "cancelling"\) \{\s*return;\s*\}',
    )
    cancel_transition = re.compile(
        r'if \(state\.phase === "streaming" && state\.activeResponseId\) \{.*?'
        r"if \(sendEvent\(cancelEvent\)\) \{\s*"
        r'state\.phase = "cancelling";\s*updateControls\(\);',
        re.DOTALL,
    )
    assert pending_guard.search(javascript)
    assert cancel_transition.search(javascript)


def test_console_events_are_correlated_to_the_active_request() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

    started_guard = re.compile(
        r'if \(state\.phase !== "pending" \|\| data\.message_id !== state\.pendingMessageId\) \{\s*return;\s*\}',
    )
    assert started_guard.search(javascript)
    assert "function matchesActiveResponse(data)" in javascript
    assert javascript.count("matchesActiveResponse(data)") >= 4
    assert "const matchesPendingError" in javascript
    assert "const matchesActiveError" in javascript


def test_console_controls_expose_waiting_and_stopping_phases() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

    assert 'state.phase === "pending" ? "Waiting"' in javascript
    assert 'state.phase === "cancelling" ? "Stopping"' in javascript
    assert 'elements.sendStop.disabled = state.phase === "pending" || state.phase === "cancelling"' in javascript
    assert 'elements.input.disabled = state.phase !== "idle"' in javascript


def test_console_socket_close_clears_request_state_on_every_phase() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

    close_reset = re.compile(
        r'if \(state\.phase !== "idle"\) \{\s*'
        r'finishGeneration\("Connection closed; the last message was not replayed\.".*?'
        r"\} else \{\s*resetRequestState\(\);\s*\}",
        re.DOTALL,
    )
    assert close_reset.search(javascript)


def test_console_node_dom_and_websocket_regressions() -> None:
    root = Path(__file__).parents[2]
    result = subprocess.run(
        ["node", "tests/js/web_console_state.mjs"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_console_view_node_boundaries() -> None:
    root = Path(__file__).parents[2]
    result = subprocess.run(
        ["node", "tests/js/console_view.mjs"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
