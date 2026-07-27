import json
from datetime import UTC

import pytest
from pydantic import ValidationError

from somai_chat.api.protocol import MessageCreate, Ping, ResponseCancel, ServerEvent, parse_client_event
from somai_chat.core.errors import ErrorCode, SomaiError


def test_error_code_values_are_stable() -> None:
    assert [code.value for code in ErrorCode] == [
        "INVALID_MESSAGE",
        "GENERATION_IN_PROGRESS",
        "CANCEL_NOT_FOUND",
        "MODEL_UNAVAILABLE",
        "GENERATION_FAILED",
    ]


def test_somai_error_exposes_only_safe_message() -> None:
    error = SomaiError(ErrorCode.MODEL_UNAVAILABLE, "Model is temporarily unavailable")

    assert error.code is ErrorCode.MODEL_UNAVAILABLE
    assert error.safe_message == "Model is temporarily unavailable"
    assert str(error) == "Model is temporarily unavailable"


def test_parse_message_create_strips_content() -> None:
    event = parse_client_event(
        {"type": "message.create", "data": {"message_id": "msg_123-ABC", "content": "  hello  "}},
        max_message_length=20,
    )

    assert isinstance(event, MessageCreate)
    assert event.data.message_id == "msg_123-ABC"
    assert event.data.content == "hello"


def test_parse_message_create_accepts_http_and_https_image_urls() -> None:
    event = parse_client_event(
        {
            "type": "message.create",
            "data": {
                "message_id": "msg_image",
                "content": "describe this",
                "image_urls": ["http://images.example.test/one.jpg", "https://images.example.test/two.png"],
            },
        },
        max_message_length=20,
    )

    assert isinstance(event, MessageCreate)
    assert event.data.image_urls == ["http://images.example.test/one.jpg", "https://images.example.test/two.png"]


def test_parse_message_create_accepts_uploaded_image_ids() -> None:
    event = parse_client_event(
        {
            "type": "message.create",
            "data": {"message_id": "msg_image", "content": "look", "image_ids": ["img_abc123"]},
        },
        max_message_length=100,
    )

    assert event.data.image_ids == ["img_abc123"]


def test_parse_action_result_accepts_camera_failure() -> None:
    event = parse_client_event(
        {
            "type": "action.result",
            "data": {
                "action": "camera.capture",
                "request_id": "cam_req_001",
                "response_id": "resp_001",
                "message_id": "msg_001",
                "status": "denied",
                "error_code": "CAMERA_PERMISSION_DENIED",
            },
        },
        max_message_length=100,
    )

    assert event.data.status == "denied"
    assert event.data.error_code == "CAMERA_PERMISSION_DENIED"


@pytest.mark.parametrize(
    "image_urls",
    [[], ["ftp://images.example.test/a.jpg"], ["not-a-url"], ["https://x.test/a"] * 5],
)
def test_parse_message_create_rejects_invalid_image_urls(image_urls: list[str]) -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(
            {
                "type": "message.create",
                "data": {"message_id": "msg_image", "content": "look", "image_urls": image_urls},
            },
            max_message_length=20,
        )

    assert_invalid_client_event(exc_info.value)


def test_parse_response_cancel() -> None:
    event = parse_client_event(
        {"type": "response.cancel", "data": {"response_id": "resp_123"}},
        max_message_length=20,
    )

    assert isinstance(event, ResponseCancel)
    assert event.data.response_id == "resp_123"


@pytest.mark.parametrize("data", [{}, {"correlation_id": "corr-123"}])
def test_parse_ping(data: dict[str, str]) -> None:
    event = parse_client_event({"type": "ping", "data": data}, max_message_length=20)

    assert isinstance(event, Ping)
    assert event.data.correlation_id == data.get("correlation_id")


@pytest.mark.parametrize(
    ("event_type", "field_name"),
    [
        ("message.create", "message_id"),
        ("response.cancel", "response_id"),
        ("ping", "correlation_id"),
    ],
)
@pytest.mark.parametrize("identifier", ["x", "x" * 128], ids=["one-character", "128-characters"])
def test_parse_client_event_accepts_identifier_boundaries(
    event_type: str,
    field_name: str,
    identifier: str,
) -> None:
    event = parse_client_event(client_event_with_id(event_type, field_name, identifier), max_message_length=20)

    assert event.data.model_dump()[field_name] == identifier


@pytest.mark.parametrize(
    ("event_type", "field_name"),
    [
        ("message.create", "message_id"),
        ("response.cancel", "response_id"),
        ("ping", "correlation_id"),
    ],
)
@pytest.mark.parametrize(
    "identifier",
    ["", "x" * 129, "invalid id", "invalid!"],
    ids=["empty", "129-characters", "space", "invalid-character"],
)
def test_parse_client_event_rejects_invalid_identifier_boundaries(
    event_type: str,
    field_name: str,
    identifier: str,
) -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(client_event_with_id(event_type, field_name, identifier), max_message_length=20)

    assert_invalid_client_event(exc_info.value)


@pytest.mark.parametrize("content", ["", "   ", "message that is too long"])
def test_parse_message_rejects_blank_or_over_limit_content(content: str) -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(
            {"type": "message.create", "data": {"message_id": "msg_123", "content": content}},
            max_message_length=10,
        )

    assert_invalid_client_event(exc_info.value)


def test_parse_message_applies_limit_after_stripping_content() -> None:
    event = parse_client_event(
        {"type": "message.create", "data": {"message_id": "msg_123", "content": " 1234567890 "}},
        max_message_length=10,
    )

    assert isinstance(event, MessageCreate)
    assert event.data.content == "1234567890"


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "message.create", "data": {"message_id": "msg_123", "content": json.loads(r'"\ud800"')}},
        {"type": json.loads(r'"\ud800"'), "data": {}},
    ],
    ids=["content", "type"],
)
def test_parse_client_event_rejects_lone_surrogates(payload: object) -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(payload, max_message_length=20)

    assert_invalid_client_event(exc_info.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "unknown", "data": {}},
        {"type": "ping", "data": {}, "unexpected": True},
        {"type": "ping", "data": {"unexpected": True}},
    ],
)
def test_parse_client_event_rejects_unknown_type_and_extra_fields(payload: object) -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(payload, max_message_length=20)

    assert_invalid_client_event(exc_info.value)


@pytest.mark.parametrize("payload", [None, [], "ping", 1, {"data": {}}, {"type": "ping"}])
def test_parse_client_event_maps_all_validation_details_to_safe_error(payload: object) -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(payload, max_message_length=20)

    assert_invalid_client_event(exc_info.value)
    assert "validation" not in str(exc_info.value).lower()
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_server_event_creates_json_ready_envelope() -> None:
    event = ServerEvent.create("response.delta", {"response_id": "resp_123", "delta": "hello"})
    payload = event.model_dump(mode="json")

    assert payload["type"] == "response.delta"
    assert payload["event_id"].startswith("evt_")
    assert len(payload["event_id"]) == len("evt_") + 32
    assert payload["timestamp"].endswith("Z")
    assert event.timestamp.tzinfo is UTC
    assert payload["data"] == {"response_id": "resp_123", "delta": "hello"}


def test_server_event_ids_are_unique() -> None:
    first = ServerEvent.create("pong", {})
    second = ServerEvent.create("pong", {})

    assert first.event_id != second.event_id


@pytest.mark.parametrize(
    "non_finite",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_server_event_rejects_nested_non_finite_numbers(non_finite: float) -> None:
    with pytest.raises(ValidationError):
        ServerEvent.create("response.completed", {"usage": {"score": non_finite}})


def test_server_event_rejects_lone_surrogate_in_type() -> None:
    with pytest.raises(ValidationError):
        ServerEvent.create(json.loads(r'"\ud800"'), {})


def test_server_event_rejects_lone_surrogate_in_data_value() -> None:
    with pytest.raises(ValidationError):
        ServerEvent.create("response.delta", {"delta": json.loads(r'"\ud800"')})


def test_server_event_rejects_lone_surrogate_in_nested_data_key() -> None:
    with pytest.raises(ValidationError):
        ServerEvent.create("response.completed", {"usage": {json.loads(r'"\ud800"'): 1}})


def test_server_event_valid_unicode_serializes_and_data_is_copied() -> None:
    data: dict[str, str] = {"message": "你好 😀"}

    event = ServerEvent.create("response.completed", data)
    data["message"] = "changed"
    payload = json.loads(event.model_dump_json())

    assert payload["data"] == {"message": "你好 😀"}


def client_event_with_id(event_type: str, field_name: str, identifier: str) -> dict[str, object]:
    data: dict[str, object] = {field_name: identifier}
    if event_type == "message.create":
        data["content"] = "hello"
    return {"type": event_type, "data": data}


def assert_invalid_client_event(error: SomaiError) -> None:
    assert error.code is ErrorCode.INVALID_MESSAGE
    assert error.safe_message == "Invalid client event"
    assert str(error) == "Invalid client event"
