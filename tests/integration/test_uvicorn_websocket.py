from __future__ import annotations

import os
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.sync.client import connect

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until_live(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"uvicorn exited early\nstdout={stdout}\nstderr={stderr}")
        try:
            with urlopen(f"http://127.0.0.1:{port}/health/live", timeout=0.2) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.02)
    raise AssertionError("uvicorn did not become live")


@contextmanager
def uvicorn_server(*, ready: bool) -> Iterator[int]:
    port = unused_port()
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith("SOMAI_") or name.lower().endswith("_proxy"):
            environment.pop(name)
    if ready:
        environment.update(
            SOMAI_OPENAI_API_KEY="test-secret",
            SOMAI_OPENAI_MODEL="test-model",
            SOMAI_ALLOWED_ORIGINS='["https://allowed.example"]',
        )
    else:
        environment.update(SOMAI_OPENAI_API_KEY="", SOMAI_OPENAI_MODEL="")
    process = subprocess.Popen(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "-m",
            "uvicorn",
            "somai_chat.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--ws-max-size",
            "32768",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_until_live(process, port)
        yield port
    finally:
        process.terminate()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)


def assert_server_close_code(port: int, path: str, expected: int, *, origin: str | None = None) -> None:
    with connect(f"ws://127.0.0.1:{port}{path}", origin=origin) as websocket:
        with pytest.raises(ConnectionClosedError) as captured:
            websocket.recv()
    assert captured.value.rcvd is not None
    assert captured.value.rcvd.code == expected


def test_real_server_invalid_conversation_closes_with_1008_after_handshake() -> None:
    with uvicorn_server(ready=True) as port:
        assert_server_close_code(port, "/api/v1/chat/ws/bad%20id", 1008)


def test_real_server_invalid_origin_closes_with_1008_after_handshake() -> None:
    with uvicorn_server(ready=True) as port:
        assert_server_close_code(
            port,
            "/api/v1/chat/ws/conv_origin",
            1008,
            origin="https://denied.example",
        )


def test_real_server_not_ready_closes_with_1013_after_handshake() -> None:
    with uvicorn_server(ready=False) as port:
        assert_server_close_code(port, "/api/v1/chat/ws/conv_unavailable", 1013)
