"""Structured application logging without sensitive payload fields."""

import json
import logging
from datetime import UTC, datetime
from typing import ClassVar


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


def configure_logging(level: str = "INFO") -> None:
    """Install the process JSON handler with the requested level."""

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
