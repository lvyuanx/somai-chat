from __future__ import annotations

import asyncio
import importlib
import io
import json
import logging
import os
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import contextmanager
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from somai_chat.agent.graph import ConversationGraph
from somai_chat.application.conversation import ConversationRuntime
from somai_chat.core.config import Settings, get_settings
from somai_chat.core.logging import JsonFormatter
from somai_chat.main import create_app


class StreamingGraph:
    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        del args, kwargs
        yield AIMessageChunk(content="你"), {}
        yield AIMessageChunk(content="好"), {}


class BlockingRuntime:
    def __init__(self) -> None:
        self.closed = threading.Event()

    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[Any]:
        from somai_chat.api.protocol import ServerEvent

        del conversation_id, content
        try:
            yield ServerEvent.create(
                "response.started",
                {"response_id": response_id, "message_id": message_id},
            )
            await asyncio.Event().wait()
        finally:
            self.closed.set()


class FailingRuntime:
    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[Any]:
        del conversation_id, message_id, content, response_id
        raise RuntimeError("provider-secret-detail")
        yield


def make_test_settings() -> Settings:
    return Settings(
        openai_api_key=SecretStr("test-secret"),
        openai_model="test-model",
        allowed_origins=["https://allowed.example"],
    )


def app_client(runtime: object | None = None, *, settings: Settings | None = None) -> TestClient:
    selected = runtime or ConversationRuntime(cast(ConversationGraph, StreamingGraph()))
    return TestClient(create_app(settings=settings or make_test_settings(), runtime=selected))


def receive_types(socket: Any, count: int) -> list[str]:
    return [socket.receive_json()["type"] for _ in range(count)]


@contextmanager
def without_model_environment() -> Any:
    names = [name for name in os.environ if name.startswith("SOMAI_")]
    saved = {name: os.environ.pop(name) for name in names}
    try:
        yield
    finally:
        os.environ.update(saved)


def test_module_import_is_safe_without_model_environment() -> None:
    get_settings.cache_clear()
    try:
        with without_model_environment():
            sys.modules.pop("somai_chat.main", None)
            module = importlib.import_module("somai_chat.main")

        with TestClient(module.app) as client:
            assert client.get("/health/live").json() == {"status": "alive"}
            response = client.get("/health/ready")
            assert response.status_code == 503
            assert response.json() == {"status": "not_ready"}
    finally:
        get_settings.cache_clear()


def test_health_live_and_ready_with_injected_dependencies() -> None:
    with app_client() as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_does_not_call_runtime() -> None:
    class NetworkTrapRuntime:
        def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            del args, kwargs
            raise AssertionError("readiness must not call the model")

    with app_client(NetworkTrapRuntime()) as client:
        assert client.get("/health/ready").json() == {"status": "ready"}


def test_websocket_streams_uniform_ordered_response() -> None:
    with app_client() as client, client.websocket_connect("/api/v1/chat/ws/conv_test") as socket:
        ready = socket.receive_json()
        socket.send_json({"type": "message.create", "data": {"message_id": "msg_test", "content": "你好"}})
        events = [socket.receive_json() for _ in range(4)]

    assert ready["type"] == "conversation.ready"
    assert [event["type"] for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.completed",
    ]
    for event in [ready, *events]:
        assert set(event) == {"type", "event_id", "timestamp", "data"}
        assert event["event_id"].startswith("evt_")
        assert event["timestamp"].endswith("Z")


@pytest.mark.parametrize("payload", ["{", json.dumps({"type": "unknown", "data": {}})])
def test_invalid_input_returns_error_and_connection_remains_usable(payload: str) -> None:
    with app_client() as client, client.websocket_connect("/api/v1/chat/ws/conv_test") as socket:
        socket.receive_json()
        socket.send_text(payload)
        error = socket.receive_json()
        socket.send_json({"type": "ping", "data": {"correlation_id": "probe"}})
        pong = socket.receive_json()

    assert error["type"] == "error"
    assert error["data"] == {"code": "INVALID_MESSAGE", "message": "Invalid client event"}
    assert pong["type"] == "pong"
    assert pong["data"] == {"correlation_id": "probe"}


def test_binary_input_returns_error_and_connection_remains_usable() -> None:
    with app_client() as client, client.websocket_connect("/api/v1/chat/ws/conv_binary") as socket:
        socket.receive_json()
        socket.send_bytes(b'{"type":"ping","data":{}}')
        error = socket.receive_json()
        socket.send_json({"type": "ping", "data": {"correlation_id": "after_binary"}})
        pong = socket.receive_json()

    assert error["data"]["code"] == "INVALID_MESSAGE"
    assert pong["data"]["correlation_id"] == "after_binary"


def test_raw_text_byte_limit_accepts_boundary_and_rejects_one_more_byte() -> None:
    payload = json.dumps(
        {"type": "message.create", "data": {"message_id": "msg_limit", "content": "hello"}},
        separators=(",", ":"),
    )
    settings = Settings(
        openai_api_key="secret",
        openai_model="model",
        max_websocket_message_bytes=len(payload.encode("utf-8")),
        allowed_origins=["https://allowed.example"],
    )
    with app_client(settings=settings) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_equal") as socket:
            socket.receive_json()
            socket.send_text(payload)
            assert receive_types(socket, 4) == [
                "response.started",
                "response.delta",
                "response.delta",
                "response.completed",
            ]
        with client.websocket_connect("/api/v1/chat/ws/conv_over") as socket:
            socket.receive_json()
            socket.send_text(payload + " ")
            assert socket.receive_json()["data"]["code"] == "INVALID_MESSAGE"
            socket.send_json({"type": "ping", "data": {}})
            assert socket.receive_json()["type"] == "pong"


@pytest.mark.parametrize(
    "payload",
    [
        '{"type":"ping","data":{"correlation_id":' + "1" * 5000 + "}}",
        '{"type":"ping","data":{"correlation_id":"\ud800"}}',
    ],
    ids=["python-integer-limit", "invalid-unicode-scalar"],
)
def test_json_value_errors_map_to_invalid_message_and_connection_recovers(payload: str) -> None:
    settings = Settings(
        openai_api_key="secret",
        openai_model="model",
        max_websocket_message_bytes=10000,
        allowed_origins=["https://allowed.example"],
    )
    with app_client(settings=settings) as client, client.websocket_connect("/api/v1/chat/ws/conv_value") as socket:
        socket.receive_json()
        socket.send_text(payload)
        assert socket.receive_json()["data"]["code"] == "INVALID_MESSAGE"
        socket.send_json({"type": "ping", "data": {}})
        assert socket.receive_json()["type"] == "pong"


def test_deeply_nested_json_maps_to_invalid_message_and_connection_recovers() -> None:
    payload = "[" * 10000 + "0" + "]" * 10000
    with app_client() as client, client.websocket_connect("/api/v1/chat/ws/conv_depth") as socket:
        socket.receive_json()
        socket.send_text(payload)
        assert socket.receive_json()["data"]["code"] == "INVALID_MESSAGE"
        socket.send_json({"type": "ping", "data": {"correlation_id": "after_depth"}})
        pong = socket.receive_json()

    assert pong["type"] == "pong"
    assert pong["data"]["correlation_id"] == "after_depth"


def test_busy_cancel_and_cancel_not_found_are_recoverable() -> None:
    runtime = BlockingRuntime()
    with app_client(runtime) as client, client.websocket_connect("/api/v1/chat/ws/conv_test") as socket:
        socket.receive_json()
        socket.send_json({"type": "message.create", "data": {"message_id": "msg_1", "content": "one"}})
        started = socket.receive_json()
        response_id = started["data"]["response_id"]
        socket.send_json({"type": "message.create", "data": {"message_id": "msg_2", "content": "two"}})
        assert socket.receive_json()["data"]["code"] == "GENERATION_IN_PROGRESS"
        socket.send_json({"type": "response.cancel", "data": {"response_id": "resp_wrong"}})
        assert socket.receive_json()["data"]["code"] == "CANCEL_NOT_FOUND"
        socket.send_json({"type": "response.cancel", "data": {"response_id": response_id}})
        assert socket.receive_json()["type"] == "response.cancelled"
        socket.send_json({"type": "ping", "data": {}})
        assert socket.receive_json()["type"] == "pong"


@pytest.mark.parametrize("conversation_id", ["bad id", "x" * 129, "é"])
def test_invalid_conversation_id_is_closed_by_policy(conversation_id: str) -> None:
    with app_client() as client:
        with client.websocket_connect(f"/api/v1/chat/ws/{conversation_id}") as socket:
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_json()
    assert captured.value.code == 1008


def test_websocket_origin_policy_allows_configured_and_device_clients() -> None:
    with app_client() as client:
        with client.websocket_connect(
            "/api/v1/chat/ws/conv_origin",
            headers={"origin": "https://allowed.example"},
        ) as socket:
            assert socket.receive_json()["type"] == "conversation.ready"
        with client.websocket_connect("/api/v1/chat/ws/conv_device") as socket:
            assert socket.receive_json()["type"] == "conversation.ready"


def test_websocket_origin_policy_normalizes_header_origin() -> None:
    with app_client() as client:
        with client.websocket_connect(
            "/api/v1/chat/ws/conv_origin",
            headers={"origin": "HTTPS://ALLOWED.EXAMPLE:443"},
        ) as socket:
            assert socket.receive_json()["type"] == "conversation.ready"


def test_websocket_origin_policy_rejects_unconfigured_origin() -> None:
    with app_client() as client:
        with client.websocket_connect(
            "/api/v1/chat/ws/conv_origin",
            headers={"origin": "https://denied.example"},
        ) as socket:
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_json()
    assert captured.value.code == 1008


def test_websocket_origin_policy_rejects_malformed_origin() -> None:
    with app_client() as client:
        with client.websocket_connect(
            "/api/v1/chat/ws/conv_origin",
            headers={"origin": "https://allowed.example/path"},
        ) as socket:
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_json()
    assert captured.value.code == 1008


def test_websocket_rejects_connection_when_runtime_is_unavailable() -> None:
    with app_client() as client:
        client.app.state.runtime = None
        client.app.state.ready = False
        with client.websocket_connect("/api/v1/chat/ws/conv_unavailable") as socket:
            with pytest.raises(WebSocketDisconnect) as captured:
                socket.receive_json()
    assert captured.value.code == 1013


def test_disconnect_closes_session_and_cancels_generation() -> None:
    runtime = BlockingRuntime()
    with app_client(runtime) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_close") as socket:
            socket.receive_json()
            socket.send_json({"type": "message.create", "data": {"message_id": "msg_1", "content": "one"}})
            assert socket.receive_json()["type"] == "response.started"
        assert runtime.closed.wait(timeout=1)


def test_runtime_error_is_safe_and_connection_remains_usable() -> None:
    with app_client(FailingRuntime()) as client, client.websocket_connect("/api/v1/chat/ws/conv_fail") as socket:
        socket.receive_json()
        socket.send_json({"type": "message.create", "data": {"message_id": "msg_safe", "content": "secret body"}})
        error = socket.receive_json()
        socket.send_json({"type": "ping", "data": {}})
        pong = socket.receive_json()

    assert error["data"]["code"] == "GENERATION_FAILED"
    assert "provider-secret-detail" not in json.dumps(error)
    assert "secret body" not in json.dumps(error)
    assert pong["type"] == "pong"


def test_json_logging_serializes_correlation_fields_without_secrets() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("somai_chat.test")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "generation failed",
        extra={
            "conversation_id": "conv_1",
            "message_id": "msg_1",
            "response_id": "resp_1",
            "error_code": "GENERATION_FAILED",
            "connection_id": "conn_1",
            "api_key": SecretStr("test-secret"),
            "content": "secret body",
        },
    )
    payload = json.loads(stream.getvalue())

    assert {"timestamp", "level", "logger", "message"} <= payload.keys()
    assert payload["conversation_id"] == "conv_1"
    assert payload["connection_id"] == "conn_1"
    serialized = json.dumps(payload)
    assert "test-secret" not in serialized
    assert "secret body" not in serialized
