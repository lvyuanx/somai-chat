from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from somai_chat.api.protocol import ServerEvent
from somai_chat.core.config import Settings
from somai_chat.core.logging import JsonFormatter
from somai_chat.main import create_app


class RecordHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class BlockingRuntime:
    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        del conversation_id, content
        yield ServerEvent.create(
            "response.started",
            {"response_id": response_id, "message_id": message_id},
        )
        await asyncio.Event().wait()


class FailingRuntime:
    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        del conversation_id, message_id, content, response_id
        raise RuntimeError("provider-secret-detail")
        yield


def make_client(runtime: object) -> TestClient:
    settings = Settings(
        environment="test",
        openai_api_key="test-api-key",
        openai_model="test-model",
        allowed_origins=["https://allowed.example"],
    )
    return TestClient(create_app(settings=settings, runtime=runtime))


@contextmanager
def capture_websocket_logs() -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger("somai_chat.api.websocket")
    handler = RecordHandler()
    previous_handlers = logger.handlers
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield handler.records
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def error_records(records: list[logging.LogRecord], code: str) -> list[logging.LogRecord]:
    return [record for record in records if getattr(record, "error_code", None) == code]


def test_invalid_message_is_logged_once_per_connection() -> None:
    with make_client(BlockingRuntime()) as client, capture_websocket_logs() as records:
        with client.websocket_connect("/api/v1/chat/ws/conv_invalid") as socket:
            socket.receive_json()
            socket.send_text("{")
            assert socket.receive_json()["data"]["code"] == "INVALID_MESSAGE"

    invalid = error_records(records, "INVALID_MESSAGE")
    assert len(invalid) == 1
    assert invalid[0].conversation_id == "conv_invalid"
    assert invalid[0].connection_id.startswith("conn_")


def test_busy_error_event_and_log_include_message_id_once() -> None:
    with make_client(BlockingRuntime()) as client, capture_websocket_logs() as records:
        with client.websocket_connect("/api/v1/chat/ws/conv_busy") as socket:
            socket.receive_json()
            socket.send_json({"type": "message.create", "data": {"message_id": "msg_1", "content": "first"}})
            socket.receive_json()
            socket.send_json({"type": "message.create", "data": {"message_id": "msg_2", "content": "second"}})
            error = socket.receive_json()

    assert error["data"]["message_id"] == "msg_2"
    busy = error_records(records, "GENERATION_IN_PROGRESS")
    assert len(busy) == 1
    assert busy[0].message_id == "msg_2"


def test_cancel_error_event_and_log_include_response_id_once() -> None:
    with make_client(BlockingRuntime()) as client, capture_websocket_logs() as records:
        with client.websocket_connect("/api/v1/chat/ws/conv_cancel") as socket:
            socket.receive_json()
            socket.send_json({"type": "response.cancel", "data": {"response_id": "resp_missing"}})
            error = socket.receive_json()

    assert error["data"]["response_id"] == "resp_missing"
    missing = error_records(records, "CANCEL_NOT_FOUND")
    assert len(missing) == 1
    assert missing[0].response_id == "resp_missing"


def test_generation_error_is_logged_once_with_all_known_ids_and_no_secrets() -> None:
    with make_client(FailingRuntime()) as client, capture_websocket_logs() as records:
        with client.websocket_connect("/api/v1/chat/ws/conv_failure") as socket:
            socket.receive_json()
            socket.send_json(
                {"type": "message.create", "data": {"message_id": "msg_failure", "content": "secret body"}}
            )
            error = socket.receive_json()

    failures = error_records(records, "GENERATION_FAILED")
    assert len(failures) == 1
    assert failures[0].connection_id.startswith("conn_")
    assert failures[0].conversation_id == "conv_failure"
    assert failures[0].message_id == "msg_failure"
    assert failures[0].response_id == error["data"]["response_id"]
    serialized = "\n".join(JsonFormatter().format(record) for record in records)
    assert "secret body" not in serialized
    assert "test-api-key" not in serialized
    assert "provider-secret-detail" not in serialized


def test_connections_have_distinct_ids_on_every_lifecycle_log() -> None:
    with make_client(BlockingRuntime()) as client, capture_websocket_logs() as records:
        for conversation_id in ("conv_one", "conv_two"):
            with client.websocket_connect(f"/api/v1/chat/ws/{conversation_id}") as socket:
                socket.receive_json()

    lifecycle_messages = {"conversation connected", "conversation disconnected"}
    lifecycle = [record for record in records if record.getMessage() in lifecycle_messages]
    assert len(lifecycle) == 4
    ids_by_conversation: dict[str, set[str]] = {}
    for record in lifecycle:
        ids_by_conversation.setdefault(record.conversation_id, set()).add(record.connection_id)
    assert {name: len(ids) for name, ids in ids_by_conversation.items()} == {"conv_one": 1, "conv_two": 1}
    assert ids_by_conversation["conv_one"].isdisjoint(ids_by_conversation["conv_two"])
