"""Structured application logging without sensitive payload fields."""

import json
import logging
from datetime import UTC, datetime
from typing import ClassVar, TextIO

_APPLICATION_LOGGER = "somai_chat"
_UNTRUSTED_LOGGERS = ("langchain", "langchain_openai", "openai", "httpx", "httpcore")


class JsonFormatter(logging.Formatter):
    """Format stable application fields as one JSON object per record."""

    correlation_fields: ClassVar[tuple[str, ...]] = (
        "connection_id",
        "conversation_id",
        "message_id",
        "response_id",
        "error_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.correlation_fields:
            value = getattr(record, field, None)
            if isinstance(value, str):
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Install an isolated JSON handler for trusted application records."""

    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    application = logging.getLogger(_APPLICATION_LOGGER)
    application.handlers = [handler]
    application.setLevel(level)
    application.propagate = False
    for name in _UNTRUSTED_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
