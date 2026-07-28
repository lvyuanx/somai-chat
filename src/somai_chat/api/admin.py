"""Versioned administrator API for robot clients."""

from datetime import datetime
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from somai_chat.admin.auth import establish_session, require_admin, require_csrf, verify_password
from somai_chat.admin.models import Client
from somai_chat.admin.presence import ClientPresenceRegistry
from somai_chat.admin.repository import ClientRepository
from somai_chat.core.logging import get_logger

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])
logger = get_logger()


class LoginInput(BaseModel):
    username: str
    password: str


class ClientInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None


class KeyRotationInput(BaseModel):
    expires_at: datetime | None = None


def _repository(request: Request) -> ClientRepository:
    return cast(ClientRepository, request.app.state.client_repository)


def _presence(request: Request) -> ClientPresenceRegistry:
    return cast(ClientPresenceRegistry, request.app.state.client_presence)


def _key_display(client: Client) -> tuple[str | None, bool]:
    active_keys = [key for key in client.access_keys if key.revoked_at is None]
    if not active_keys:
        return None, False
    active_key = max(active_keys, key=lambda key: key.created_at)
    masked_key_id = f"{active_key.key_id[:4]}••••{active_key.key_id[-4:]}"
    return f"somai_sk_{masked_key_id}_••••••••", active_key.encrypted_key is not None


@router.post("/session")
async def login(request: Request, payload: LoginInput) -> dict[str, object]:
    settings = request.app.state.settings
    if (
        settings is None
        or payload.username != settings.admin_username
        or not verify_password(payload.password, settings.admin_password.get_secret_value())
    ):
        logger.warning("管理员登录失败")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    response = {"username": settings.admin_username, "csrf_token": establish_session(request, settings.admin_username)}
    logger.info("管理员登录成功")
    return response


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    require_csrf(request)
    request.session.clear()
    logger.info("管理员退出登录")


@router.get("/session")
async def session(request: Request) -> dict[str, str]:
    username = require_admin(request)
    logger.info("管理员会话已检查")
    return {"username": username, "csrf_token": request.session["csrf"]}


@router.get("/clients")
async def list_clients(request: Request) -> list[dict[str, object]]:
    require_admin(request)
    clients = await _repository(request).list()
    online_client_ids = await _presence(request).online_client_ids()
    results: list[dict[str, object]] = []
    for client in clients:
        key_masked, can_reveal_key = _key_display(client)
        results.append(
            {
                "id": str(client.id),
                "name": client.name,
                "description": client.description,
                "enabled": client.enabled,
                "online": client.id in online_client_ids,
                "last_authenticated_at": client.last_authenticated_at,
                "key_masked": key_masked,
                "can_reveal_key": can_reveal_key,
            }
        )
    logger.bind(client_count=len(results), online_count=len(online_client_ids)).info("管理员查看客户端列表")
    return results


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(request: Request, payload: ClientInput) -> dict[str, object]:
    require_csrf(request)
    try:
        client, key = await _repository(request).create(payload.name.strip(), payload.description, payload.expires_at)
    except IntegrityError as error:
        if getattr(error.orig, "args", (None,))[0] == 1062 or "duplicate" in str(error.orig).lower():
            raise HTTPException(status_code=409, detail="Client name already exists") from None
        raise
    logger.bind(client_id=str(client.id)).info("管理员创建客户端")
    return {"id": str(client.id), "name": client.name, "key": key}


@router.post("/clients/{client_id}/enabled")
async def set_client_enabled(request: Request, client_id: UUID, enabled: bool) -> dict[str, bool]:
    require_csrf(request)
    if not await _repository(request).set_enabled(client_id, enabled):
        raise HTTPException(status_code=404, detail="Client not found")
    logger.bind(client_id=str(client_id), enabled=enabled).info("管理员修改客户端启用状态")
    return {"enabled": enabled}


@router.post("/clients/{client_id}/keys/rotate")
async def rotate_key(request: Request, client_id: UUID, payload: KeyRotationInput) -> dict[str, str]:
    require_csrf(request)
    key = await _repository(request).rotate(client_id, payload.expires_at)
    if key is None:
        raise HTTPException(status_code=404, detail="Client not found")
    logger.bind(client_id=str(client_id)).info("管理员轮换客户端 Key")
    return {"key": key}


@router.post("/clients/{client_id}/key/reveal")
async def reveal_key(request: Request, client_id: UUID) -> dict[str, str]:
    require_csrf(request)
    key = await _repository(request).reveal_key(client_id)
    if key is None:
        raise HTTPException(status_code=404, detail="Key cannot be revealed; rotate it to create a new key")
    logger.bind(client_id=str(client_id)).info("管理员查看客户端 Key")
    return {"key": key}
