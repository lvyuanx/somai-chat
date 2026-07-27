"""Translate LangGraph model and tool lifecycle events into safe workflow nodes."""

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import JsonValue

from somai_chat.api.protocol import ServerEvent

WORKFLOW_PAYLOAD_CODE_POINTS = 12_000
_MAX_DEPTH = 8
_MAX_COLLECTION_ITEMS = 100
_REDACTED = "[REDACTED]"
_TRUNCATED = "… [truncated]"
_SENSITIVE_SUFFIXES = ("apikey", "authorization", "token", "secret", "password", "credential", "clientkey")


def _unicode_scalar_text(value: str) -> tuple[str, bool]:
    normalized = "".join("�" if 0xD800 <= ord(character) <= 0xDFFF else character for character in value)
    return normalized, normalized != value


def _sensitive_key(value: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(value).lower())
    return any(normalized.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES)


def _normalize(value: object, depth: int = 0) -> tuple[JsonValue, bool]:
    if depth >= _MAX_DEPTH:
        return _TRUNCATED, True
    if isinstance(value, BaseMessage):
        return _normalize(value.content, depth)
    if value is None or isinstance(value, bool | int):
        return value, False
    if isinstance(value, float):
        return (value, False) if math.isfinite(value) else (str(value), True)
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                return _normalize(json.loads(value), depth)
            except (TypeError, ValueError, RecursionError):
                pass
        return _unicode_scalar_text(value)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        truncated = len(value) > _MAX_COLLECTION_ITEMS
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_COLLECTION_ITEMS:
                break
            name, key_truncated = _unicode_scalar_text(str(key))
            truncated = truncated or key_truncated
            if _sensitive_key(name):
                result[name] = _REDACTED
                continue
            result[name], child_truncated = _normalize(item, depth + 1)
            truncated = truncated or child_truncated
        return result, truncated
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        items: list[JsonValue] = []
        truncated = len(value) > _MAX_COLLECTION_ITEMS
        for item in value[:_MAX_COLLECTION_ITEMS]:
            normalized, child_truncated = _normalize(item, depth + 1)
            items.append(normalized)
            truncated = truncated or child_truncated
        return items, truncated
    if isinstance(value, bytes | bytearray):
        return "[binary content omitted]", True
    try:
        return str(value), True
    except Exception:
        return f"[{type(value).__name__}]", True


def _bounded_preview(serialized: str, limit: int) -> str:
    points = list(serialized)
    keep = max(0, limit - len(_TRUNCATED) - 2)
    preview = "".join(points[:keep]) + _TRUNCATED
    while len(json.dumps(preview, ensure_ascii=False)) > limit and keep > 0:
        keep -= 1
        preview = "".join(points[:keep]) + _TRUNCATED
    return preview


def sanitize_workflow_payload(value: object) -> tuple[JsonValue, bool]:
    """Return a redacted, JSON-safe and display-bounded tool payload."""
    normalized, truncated = _normalize(value)
    serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= WORKFLOW_PAYLOAD_CODE_POINTS:
        return normalized, truncated
    return _bounded_preview(serialized, WORKFLOW_PAYLOAD_CODE_POINTS), True


@dataclass(frozen=True)
class _ActiveNode:
    kind: str
    name: str
    started_at: float


class WorkflowEventTranslator:
    """Correlate graph run IDs and emit one stable event per node transition."""

    def __init__(self, response_id: str, clock: Callable[[], float] = monotonic) -> None:
        self._response_id = response_id
        self._clock = clock
        self._active: dict[str, _ActiveNode] = {}

    @staticmethod
    def _run_id(event: Mapping[str, Any]) -> str | None:
        value = event.get("run_id")
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _node_id(run_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "", run_id.replace("-", ""))
        return f"node_{safe}"[:128]

    @staticmethod
    def _kind(event_type: str) -> str | None:
        if event_type.startswith("on_chat_model_"):
            return "model"
        if event_type.startswith("on_tool_"):
            return "tool"
        return None

    @staticmethod
    def _name(event: Mapping[str, Any], kind: str) -> str:
        if kind == "model":
            return "model"
        value = event.get("name")
        name = str(value).strip() if value is not None else ""
        name, _replaced = _unicode_scalar_text(name)
        return name[:128] or "tool"

    def translate(self, event: Mapping[str, Any]) -> ServerEvent | None:
        event_type = event.get("event")
        run_id = self._run_id(event)
        if not isinstance(event_type, str) or run_id is None:
            return None
        kind = self._kind(event_type)
        if kind is None:
            return None
        node_id = self._node_id(run_id)
        if event_type.endswith("_start"):
            name = self._name(event, kind)
            self._active[run_id] = _ActiveNode(kind, name, self._clock())
            data: dict[str, JsonValue] = {
                "response_id": self._response_id,
                "node_id": node_id,
                "kind": kind,
                "name": name,
            }
            if kind == "tool":
                payload, truncated = sanitize_workflow_payload(event.get("data", {}).get("input"))
                data.update({"input": payload, "input_truncated": truncated})
            return ServerEvent.create("workflow.node.started", data)
        active = self._active.pop(run_id, None)
        if active is None:
            return None
        duration_ms = round(max(0.0, self._clock() - active.started_at) * 1000)
        data = {"response_id": self._response_id, "node_id": node_id, "duration_ms": duration_ms}
        if event_type.endswith("_end"):
            if active.kind == "tool":
                payload, truncated = sanitize_workflow_payload(event.get("data", {}).get("output"))
                data.update({"output": payload, "output_truncated": truncated})
            return ServerEvent.create("workflow.node.completed", data)
        if event_type.endswith("_error"):
            return ServerEvent.create("workflow.node.failed", data)
        self._active[run_id] = active
        return None
