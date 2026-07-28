"""Versioned WebSocket transport for conversation sessions."""

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import cast
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from somai_chat.admin.presence import ClientPresenceRegistry
from somai_chat.admin.repository import ClientRepository
from somai_chat.api.protocol import ActionResult, MessageCreate, Ping, ResponseCancel, ServerEvent, parse_client_event
from somai_chat.application.conversation import ConversationRuntime, ConversationSession
from somai_chat.core.config import Settings, normalize_origin
from somai_chat.core.errors import ErrorCode, SomaiError
from somai_chat.core.logging import get_logger

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
logger = get_logger()
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


def _current_request_origin(websocket: WebSocket) -> str | None:
    host = websocket.headers.get("host")
    if not host:
        return None
    scheme = "https" if websocket.url.scheme == "wss" else "http"
    try:
        return normalize_origin(f"{scheme}://{host}")
    except ValueError:
        return None


def _origin_is_allowed(websocket: WebSocket, normalized_origin: str, settings: Settings) -> bool:
    return normalized_origin in settings.allowed_origins or normalized_origin == _current_request_origin(websocket)


def _uploaded_image_urls(image_ids: list[str], server_port: int) -> tuple[str, ...]:
    return tuple(f"http://127.0.0.1:{server_port}/api/v1/images/{image_id}" for image_id in image_ids)


def _camera_failure_message(status: str, error_code: str | None) -> str:
    messages = {
        "CAMERA_UNAVAILABLE": "抱歉，当前设备摄像头不可用，暂时无法查看。",
        "CAMERA_PERMISSION_DENIED": "抱歉，我没有获得摄像头权限，暂时无法查看。",
        "CAMERA_CAPTURE_FAILED": "抱歉，这次拍照失败了，暂时无法查看。",
        "CAMERA_CAPTURE_CANCELLED": "好的，我已取消这次拍照。",
        "IMAGE_UPLOAD_FAILED": "抱歉，图片上传失败了，暂时无法识别。",
        "IMAGE_UPLOAD_TIMEOUT": "抱歉，图片上传超时了，暂时无法识别。",
    }
    if error_code in messages:
        return messages[error_code]
    if status == "denied":
        return messages["CAMERA_PERMISSION_DENIED"]
    if status == "cancelled":
        return messages["CAMERA_CAPTURE_CANCELLED"]
    return "抱歉，我这次没能完成拍照，暂时无法查看。"


async def _send_camera_failure(send: Callable[[ServerEvent], Awaitable[None]], result: ActionResult) -> None:
    data = result.data
    content = _camera_failure_message(data.status, data.error_code)
    await send(ServerEvent.create("response.started", {"response_id": data.response_id, "message_id": data.message_id}))
    await send(ServerEvent.create("response.delta", {"response_id": data.response_id, "delta": content}))
    await send(
        ServerEvent.create("response.completed", {"response_id": data.response_id, "content": content, "usage": None})
    )


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
    connection_logger = logger.bind(connection_id=connection_id)
    settings = cast(Settings | None, getattr(websocket.app.state, "settings", None))
    runtime = cast(ConversationRuntime | None, getattr(websocket.app.state, "runtime", None))
    repository = cast(ClientRepository | None, getattr(websocket.app.state, "client_repository", None))
    presence = cast(ClientPresenceRegistry | None, getattr(websocket.app.state, "client_presence", None))
    origin = websocket.headers.get("origin")
    await websocket.accept()
    if _CONVERSATION_ID.fullmatch(conversation_id) is None:
        connection_logger.bind(reject_reason="invalid_conversation_id").info("对话连接被拒绝")
        await websocket.close(code=1008)
        return
    connection_logger = connection_logger.bind(conversation_id=conversation_id)
    if settings is None or runtime is None or not websocket.app.state.ready:
        connection_logger.bind(reject_reason="runtime_unavailable").info("对话连接被拒绝")
        await websocket.close(code=1013)
        return
    if origin is not None:
        try:
            normalized_origin = normalize_origin(origin)
        except ValueError:
            connection_logger.bind(reject_reason="invalid_origin").info("对话连接被拒绝")
            await websocket.close(code=1008)
            return
        if not _origin_is_allowed(websocket, normalized_origin, settings):
            connection_logger.bind(reject_reason="origin_not_allowed").info("对话连接被拒绝")
            await websocket.close(code=1008)
            return
    admin_session = websocket.scope.get("session")
    is_administrator = settings.environment == "test" or (
        isinstance(admin_session, dict) and isinstance(admin_session.get("admin"), str)
    )
    client_id = None
    if not is_administrator:
        authorization = websocket.headers.get("authorization", "")
        if repository is None or not authorization.startswith("Bearer "):
            connection_logger.bind(reject_reason="missing_authorization").info("对话连接被拒绝")
            await websocket.close(code=1008)
            return
        client = await repository.authenticate(authorization.removeprefix("Bearer "))
        if client is None:
            connection_logger.bind(reject_reason="invalid_client_key").info("对话连接被拒绝")
            await websocket.close(code=1008)
            return
        client_id = client.id
    send_lock = asyncio.Lock()

    async def raw_send(event: ServerEvent) -> None:
        async with send_lock:
            await websocket.send_json(event.model_dump(mode="json"))

    async def session_send(event: ServerEvent) -> None:
        if event.type == "error":
            data = event.data
            connection_logger.bind(
                message_id=data.get("message_id"),
                response_id=data.get("response_id"),
                error_code=data.get("code"),
            ).warning("对话生成错误")
        await raw_send(event)

    is_registered = False
    if client_id is not None:
        if presence is None:
            connection_logger.bind(reject_reason="presence_unavailable").info("对话连接被拒绝")
            await websocket.close(code=1013)
            return
        previous_connection = await presence.replace(
            client_id,
            connection_id,
            lambda: websocket.close(code=4001),
        )
        if previous_connection is not None:
            await previous_connection.close()
        is_registered = True
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
        connection_logger.info("对话已连接")
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
                event = parse_client_event(payload, settings.max_message_length, settings.max_image_urls)
                if isinstance(event, MessageCreate):
                    message_id = event.data.message_id
                    connection_logger.bind(
                        event_type=event.type,
                        message_id=message_id,
                        image_count=len(event.data.image_urls or event.data.image_ids or ()),
                    ).info("收到对话事件")
                    image_urls = tuple(event.data.image_urls or ())
                    if event.data.image_ids is not None:
                        image_urls = _uploaded_image_urls(event.data.image_ids, settings.port)
                    response_id = session.start(event.data.message_id, event.data.content, image_urls)
                    connection_logger.bind(message_id=message_id, response_id=response_id).info("对话生成开始")
                elif isinstance(event, ActionResult):
                    connection_logger.bind(
                        event_type=event.type,
                        message_id=event.data.message_id,
                        response_id=event.data.response_id,
                    ).info("收到对话事件")
                    if event.data.status != "success":
                        await _send_camera_failure(raw_send, event)
                elif isinstance(event, ResponseCancel):
                    response_id = event.data.response_id
                    connection_logger.bind(event_type=event.type, response_id=response_id).info("收到对话事件")
                    await session.cancel(event.data.response_id)
                    connection_logger.bind(response_id=response_id).info("请求取消对话生成")
                elif isinstance(event, Ping):
                    connection_logger.bind(event_type=event.type).info("收到对话事件")
                    await raw_send(ServerEvent.create("pong", {"correlation_id": event.data.correlation_id}))
            except SomaiError as safe_error:
                connection_logger.bind(
                    message_id=message_id,
                    response_id=response_id,
                    error_code=safe_error.code,
                ).info("对话请求错误")
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
            if is_registered and client_id is not None and presence is not None:
                await presence.disconnect(client_id, connection_id)
            connection_logger.info("对话已断开")
