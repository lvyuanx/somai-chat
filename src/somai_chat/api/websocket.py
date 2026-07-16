"""Versioned WebSocket transport for conversation sessions."""

import asyncio
import json
import logging
import re
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from somai_chat.api.protocol import MessageCreate, Ping, ResponseCancel, ServerEvent, parse_client_event
from somai_chat.application.conversation import ConversationRuntime, ConversationSession
from somai_chat.core.config import Settings, normalize_origin
from somai_chat.core.errors import ErrorCode, SomaiError

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = logging.getLogger(__name__)
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$", re.ASCII)


def _error_event(
    error: SomaiError,
    *,
    message_id: str | None = None,
    response_id: str | None = None,
) -> ServerEvent:
    data: dict[str, str] = {"code": error.code, "message": error.safe_message}
    if message_id is not None:
        data["message_id"] = message_id
    if response_id is not None:
        data["response_id"] = response_id
    return ServerEvent.create("error", data)


def _invalid_message() -> SomaiError:
    return SomaiError(ErrorCode.INVALID_MESSAGE, "Invalid client event")


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


async def _receive_text(websocket: WebSocket, max_bytes: int) -> str:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000), message.get("reason", ""))
    text = message.get("text")
    if not isinstance(text, str):
        raise _invalid_message()
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise _invalid_message() from None
    if len(encoded) > max_bytes:
        raise _invalid_message()
    return text


@router.websocket("/ws/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: str) -> None:
    connection_id = f"conn_{uuid4().hex}"
    log_context = {"connection_id": connection_id, "conversation_id": conversation_id}
    settings = cast(Settings | None, getattr(websocket.app.state, "settings", None))
    runtime = cast(ConversationRuntime | None, getattr(websocket.app.state, "runtime", None))
    origin = websocket.headers.get("origin")
    await websocket.accept()
    if _CONVERSATION_ID.fullmatch(conversation_id) is None:
        logger.info("conversation rejected", extra=log_context)
        await websocket.close(code=1008)
        return
    if settings is None or runtime is None or not websocket.app.state.ready:
        logger.info("conversation rejected", extra=log_context)
        await websocket.close(code=1013)
        return
    if origin is not None:
        try:
            normalized_origin = normalize_origin(origin)
        except ValueError:
            logger.info("conversation rejected", extra=log_context)
            await websocket.close(code=1008)
            return
        if normalized_origin not in settings.allowed_origins:
            logger.info("conversation rejected", extra=log_context)
            await websocket.close(code=1008)
            return
    send_lock = asyncio.Lock()

    async def raw_send(event: ServerEvent) -> None:
        async with send_lock:
            await websocket.send_json(event.model_dump(mode="json"))

    async def session_send(event: ServerEvent) -> None:
        if event.type == "error":
            data = event.data
            logger.warning(
                "conversation generation error",
                extra={
                    **log_context,
                    "message_id": data.get("message_id"),
                    "response_id": data.get("response_id"),
                    "error_code": data.get("code"),
                },
            )
        await raw_send(event)

    session = ConversationSession(conversation_id, runtime, session_send)
    try:
        await raw_send(
            ServerEvent.create(
                "conversation.ready",
                {
                    "conversation_id": conversation_id,
                    "max_message_length": settings.max_message_length,
                    "max_websocket_message_bytes": settings.max_websocket_message_bytes,
                    "model": settings.openai_model,
                },
            )
        )
        logger.info("conversation connected", extra=log_context)
        while True:
            message_id: str | None = None
            response_id: str | None = None
            try:
                text = await _receive_text(websocket, settings.max_websocket_message_bytes)
                try:
                    payload = json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
                except json.JSONDecodeError:
                    raise _invalid_message() from None
                except (ValueError, UnicodeEncodeError, RecursionError):
                    raise _invalid_message() from None
                event = parse_client_event(payload, settings.max_message_length)
                if isinstance(event, MessageCreate):
                    message_id = event.data.message_id
                    session.start(event.data.message_id, event.data.content)
                elif isinstance(event, ResponseCancel):
                    response_id = event.data.response_id
                    await session.cancel(event.data.response_id)
                elif isinstance(event, Ping):
                    await raw_send(ServerEvent.create("pong", {"correlation_id": event.data.correlation_id}))
            except SomaiError as safe_error:
                logger.info(
                    "conversation request error",
                    extra={
                        **log_context,
                        "message_id": message_id,
                        "response_id": response_id,
                        "error_code": safe_error.code,
                    },
                )
                await raw_send(
                    _error_event(
                        safe_error,
                        message_id=message_id,
                        response_id=response_id,
                    )
                )
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await session.close()
        finally:
            logger.info("conversation disconnected", extra=log_context)
