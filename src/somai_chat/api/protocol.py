from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from somai_chat.core.errors import ErrorCode, SomaiError

type Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
]


def _validate_unicode_scalars(value: object) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, BaseModel):
        for field_value in vars(value).values():
            _validate_unicode_scalars(field_value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _validate_unicode_scalars(key)
            _validate_unicode_scalars(item)
    elif isinstance(value, list):
        for item in value:
            _validate_unicode_scalars(item)


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_unicode_scalars(self) -> Self:
        try:
            _validate_unicode_scalars(self)
        except UnicodeEncodeError:
            raise ValueError("Protocol strings must contain only Unicode scalar values") from None
        return self


class MessageCreateData(ProtocolModel):
    message_id: Identifier
    content: str

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class MessageCreate(ProtocolModel):
    type: Literal["message.create"]
    data: MessageCreateData


class ResponseCancelData(ProtocolModel):
    response_id: Identifier


class ResponseCancel(ProtocolModel):
    type: Literal["response.cancel"]
    data: ResponseCancelData


class PingData(ProtocolModel):
    correlation_id: Identifier | None = None


class Ping(ProtocolModel):
    type: Literal["ping"]
    data: PingData


type ClientEvent = Annotated[
    MessageCreate | ResponseCancel | Ping,
    Field(discriminator="type"),
]

_CLIENT_EVENT_ADAPTER: TypeAdapter[ClientEvent] = TypeAdapter(ClientEvent)


def parse_client_event(payload: object, max_message_length: int) -> ClientEvent:
    event: ClientEvent | None
    try:
        event = _CLIENT_EVENT_ADAPTER.validate_python(payload)
    except ValidationError:
        event = None

    invalid_content = isinstance(event, MessageCreate) and (
        not event.data.content or len(event.data.content) > max_message_length
    )
    if event is None or invalid_content:
        raise SomaiError(ErrorCode.INVALID_MESSAGE, "Invalid client event")
    return event


class ServerEvent(ProtocolModel):
    type: str
    event_id: str
    timestamp: datetime
    data: dict[str, JsonValue]

    @classmethod
    def create(cls, event_type: str, data: Mapping[str, JsonValue]) -> "ServerEvent":
        return cls(
            type=event_type,
            event_id=f"evt_{uuid4().hex}",
            timestamp=datetime.now(UTC),
            data=dict(data),
        )
