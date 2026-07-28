from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from somai_chat.api.protocol import ServerEvent
from somai_chat.core.config import Settings
from somai_chat.main import create_app


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


def read_project_log(tmp_path: Path) -> str:
    return (tmp_path / "logs" / f"{date.today().isoformat()}-project.log").read_text(encoding="utf-8")


def extract_field(line: str, field: str) -> str:
    match = re.search(rf"{field}=([^| ]+)", line)
    assert match is not None
    return match.group(1)


def project_lines(log_text: str, message: str) -> list[str]:
    return [line for line in log_text.splitlines() if message in line]


def test_invalid_message_is_logged_once_per_connection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(BlockingRuntime()) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_invalid") as socket:
            socket.receive_json()
            socket.send_text("{")
            assert socket.receive_json()["data"]["code"] == "INVALID_MESSAGE"

    log_text = read_project_log(tmp_path)
    lines = project_lines(log_text, "对话请求错误")
    assert len(lines) == 1
    assert "错误码=INVALID_MESSAGE" in lines[0]
    assert "会话ID=conv_invalid" in lines[0]
    assert "连接ID=conn_" in lines[0]


def test_rejected_connection_logs_safe_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(BlockingRuntime()) as client:
        with client.websocket_connect("/api/v1/chat/ws/invalid.conversation") as socket:
            assert socket.receive() == {"type": "websocket.close", "code": 1008, "reason": ""}

    log_text = read_project_log(tmp_path)
    lines = project_lines(log_text, "对话连接被拒绝")
    assert len(lines) == 1
    assert "拒绝原因=会话ID非法" in lines[0]
    assert "会话ID=invalid.conversation" not in lines[0]


def test_message_and_cancel_events_emit_simple_project_logs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(BlockingRuntime()) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_events") as socket:
            socket.receive_json()
            socket.send_json({"type": "message.create", "data": {"message_id": "msg_1", "content": "secret body"}})
            started = socket.receive_json()
            socket.send_json({"type": "response.cancel", "data": {"response_id": started["data"]["response_id"]}})
            socket.receive_json()

    log_text = read_project_log(tmp_path)
    assert "收到对话事件" in log_text
    assert "对话生成开始" in log_text
    assert "请求取消对话生成" in log_text
    assert "事件类型=创建消息" in log_text
    assert "事件类型=取消回复" in log_text
    assert "消息ID=msg_1" in log_text
    assert f"回复ID={started['data']['response_id']}" in log_text
    assert "secret body" not in log_text


def test_busy_error_event_and_log_include_message_id_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(BlockingRuntime()) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_busy") as socket:
            socket.receive_json()
            socket.send_json({"type": "message.create", "data": {"message_id": "msg_1", "content": "first"}})
            socket.receive_json()
            socket.send_json({"type": "message.create", "data": {"message_id": "msg_2", "content": "second"}})
            error = socket.receive_json()

    log_text = read_project_log(tmp_path)
    lines = project_lines(log_text, "对话请求错误")
    assert error["data"]["message_id"] == "msg_2"
    assert len(lines) == 1
    assert "错误码=GENERATION_IN_PROGRESS" in lines[0]
    assert "消息ID=msg_2" in lines[0]


def test_cancel_error_event_and_log_include_response_id_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(BlockingRuntime()) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_cancel") as socket:
            socket.receive_json()
            socket.send_json({"type": "response.cancel", "data": {"response_id": "resp_missing"}})
            error = socket.receive_json()

    log_text = read_project_log(tmp_path)
    lines = project_lines(log_text, "对话请求错误")
    assert error["data"]["response_id"] == "resp_missing"
    assert len(lines) == 1
    assert "错误码=CANCEL_NOT_FOUND" in lines[0]
    assert "回复ID=resp_missing" in lines[0]


def test_generation_error_is_logged_once_with_all_known_ids_and_no_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(FailingRuntime()) as client:
        with client.websocket_connect("/api/v1/chat/ws/conv_failure") as socket:
            socket.receive_json()
            socket.send_json(
                {"type": "message.create", "data": {"message_id": "msg_failure", "content": "secret body"}}
            )
            error = socket.receive_json()

    log_text = read_project_log(tmp_path)
    lines = project_lines(log_text, "对话生成错误")
    assert len(lines) == 1
    assert "错误码=GENERATION_FAILED" in lines[0]
    assert "连接ID=conn_" in lines[0]
    assert "会话ID=conv_failure" in lines[0]
    assert "消息ID=msg_failure" in lines[0]
    assert f"回复ID={error['data']['response_id']}" in lines[0]
    assert "secret body" not in log_text
    assert "test-api-key" not in log_text
    assert "provider-secret-detail" not in log_text


def test_connections_have_distinct_ids_on_every_lifecycle_log(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with make_client(BlockingRuntime()) as client:
        for conversation_id in ("conv_one", "conv_two"):
            with client.websocket_connect(f"/api/v1/chat/ws/{conversation_id}") as socket:
                socket.receive_json()

    log_text = read_project_log(tmp_path)
    lifecycle = [line for line in log_text.splitlines() if "对话已连接" in line or "对话已断开" in line]
    assert len(lifecycle) == 4
    ids_by_conversation: dict[str, set[str]] = {}
    for line in lifecycle:
        ids_by_conversation.setdefault(extract_field(line, "会话ID"), set()).add(extract_field(line, "连接ID"))
    assert {name: len(ids) for name, ids in ids_by_conversation.items()} == {"conv_one": 1, "conv_two": 1}
    assert ids_by_conversation["conv_one"].isdisjoint(ids_by_conversation["conv_two"])
