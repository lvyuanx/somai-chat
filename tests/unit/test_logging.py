import io
import json
import logging
from datetime import date
from pathlib import Path

import pytest

from somai_chat.core.logging import JsonFormatter, configure_logging


def _dated_log(tmp_path: Path, suffix: str) -> Path:
    return tmp_path / "logs" / f"{date.today().isoformat()}-{suffix}.log"


def test_configure_logging_routes_project_records_to_project_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    stream = io.StringIO()

    configure_logging("INFO", stream=stream)
    logging.getLogger("somai_chat.logging_route").info("fixed event", extra={"conversation_id": "conv_1"})

    project_log = _dated_log(tmp_path, "project")
    assert "fixed event" in stream.getvalue()
    assert project_log.is_file()
    assert "fixed event" in project_log.read_text(encoding="utf-8")


def test_configure_logging_routes_errors_to_error_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    configure_logging("INFO", stream=io.StringIO())
    logging.getLogger("somai_chat.logging_route").error("failed")

    error_log = _dated_log(tmp_path, "error")
    assert error_log.is_file()
    assert "failed" in error_log.read_text(encoding="utf-8")


def test_standard_logging_is_intercepted_without_replacing_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    root_handler = logging.StreamHandler(io.StringIO())
    root.handlers = [root_handler]
    try:
        configure_logging("INFO", stream=io.StringIO())
        logging.getLogger("somai_chat.logging_route").info("fixed event")

        assert root.handlers == [root_handler]
        project_log = _dated_log(tmp_path, "project")
        assert project_log.is_file()
        assert "fixed event" in project_log.read_text(encoding="utf-8")
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


def test_json_formatter_keeps_only_safe_correlation_fields() -> None:
    record = logging.LogRecord(
        "somai_chat.logging_route",
        logging.INFO,
        __file__,
        1,
        "fixed event",
        (),
        None,
    )
    record.connection_id = "conn_1"
    record.conversation_id = "conv_1"
    record.message_id = "msg_1"
    record.response_id = "resp_1"
    record.error_code = "INVALID_MESSAGE"
    record.user_content = "secret body"
    record.api_key = "test-api-key"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "fixed event"
    assert payload["connection_id"] == "conn_1"
    assert payload["conversation_id"] == "conv_1"
    assert payload["message_id"] == "msg_1"
    assert payload["response_id"] == "resp_1"
    assert payload["error_code"] == "INVALID_MESSAGE"
    assert "secret body" not in json.dumps(payload)
    assert "test-api-key" not in json.dumps(payload)
