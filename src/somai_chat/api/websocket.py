"""Versioned WebSocket transport for conversation sessions."""

import asyncio
import json
import logging
import re
from typing import cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from somai_chat.api.protocol import MessageCreate, Ping, ResponseCancel, ServerEvent, parse_client_event
from somai_chat.application.conversation import ConversationRuntime, ConversationSession
from somai_chat.core.config import Settings
from somai_chat.core.errors import ErrorCode, SomaiError

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = logging.getLogger(__name__)
_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$", re.ASCII)


def _error_event(error: SomaiError) -> ServerEvent:
    return ServerEvent.create("error", {"code": error.code, "message": error.safe_message})


@router.websocket("/ws/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: str) -> None:
    settings = cast(Settings | None, getattr(websocket.app.state, "settings", None))
    runtime = cast(ConversationRuntime | None, getattr(websocket.app.state, "runtime", None))
    origin = websocket.headers.get("origin")
    if _CONVERSATION_ID.fullmatch(conversation_id) is None:
        await websocket.close(code=1008)
        return
    if settings is None or runtime is None or not websocket.app.state.ready:
        await websocket.close(code=1013)
        return
    if origin is not None and origin not in settings.allowed_origins:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    send_lock = asyncio.Lock()

    async def send(event: ServerEvent) -> None:
        if event.type == "error":
            data = event.data
            logger.warning(
                "conversation generation error",
                extra={
                    "conversation_id": conversation_id,
                    "message_id": data.get("message_id"),
                    "response_id": data.get("response_id"),
                    "error_code": data.get("code"),
                },
            )
        async with send_lock:
            await websocket.send_json(event.model_dump(mode="json"))

    session = ConversationSession(conversation_id, runtime, send)
    try:
        await send(ServerEvent.create("conversation.ready", {"conversation_id": conversation_id}))
        logger.info("conversation connected", extra={"conversation_id": conversation_id})
        while True:
            try:
                payload = json.loads(await websocket.receive_text())
                event = parse_client_event(payload, settings.max_message_length)
                if isinstance(event, MessageCreate):
                    session.start(event.data.message_id, event.data.content)
                elif isinstance(event, ResponseCancel):
                    await session.cancel(event.data.response_id)
                elif isinstance(event, Ping):
                    await send(ServerEvent.create("pong", {"correlation_id": event.data.correlation_id}))
            except (json.JSONDecodeError, SomaiError) as error:
                safe_error = (
                    error
                    if isinstance(error, SomaiError)
                    else SomaiError(ErrorCode.INVALID_MESSAGE, "Invalid client event")
                )
                logger.info(
                    "recoverable conversation error",
                    extra={"conversation_id": conversation_id, "error_code": safe_error.code},
                )
                await send(_error_event(safe_error))
    except WebSocketDisconnect:
        logger.info("conversation disconnected", extra={"conversation_id": conversation_id})
    finally:
        await session.close()
