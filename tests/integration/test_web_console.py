from __future__ import annotations

import re

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
        'aria-live="polite"',
        'for="message-input"',
        'id="message-input"',
        'id="send-stop"',
        'id="event-trace"',
        'src="/assets/app.js"',
        'href="/assets/app.css"',
    )
    assert all(fragment in html for fragment in required_fragments)
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE)
    assert not re.search(r"(?:src|href)=[\"']https?://", html, re.IGNORECASE)


def test_debug_console_assets_are_served_with_expected_content_types() -> None:
    with TestClient(create_app()) as client:
        stylesheet = client.get("/assets/app.css")
        script = client.get("/assets/app.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]


def test_console_styles_cover_responsive_accessible_streaming_states() -> None:
    with TestClient(create_app()) as client:
        css = client.get("/assets/app.css").text

    assert "@media (max-width: 850px)" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ".streaming-cursor" in css
    assert "--signal-orange" in css
    assert "--success-green" in css


def test_console_script_uses_safe_dom_and_websocket_state_machine() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

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
    assert not any(token in javascript for token in forbidden)
    assert all(token in javascript for token in required)


def test_console_message_send_enters_pending_synchronously() -> None:
    with TestClient(create_app()) as client:
        javascript = client.get("/assets/app.js").text

    assert 'phase: "idle"' in javascript
    assert "pendingMessageId: null" in javascript
    assert "generating" not in javascript
    transition = re.compile(
        r"if \(sendEvent\(event\)\) \{\s*"
        r"state\.pendingMessageId = messageId;\s*"
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
