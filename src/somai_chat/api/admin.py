"""Versioned administrator API for robot clients."""

from datetime import datetime
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from somai_chat.admin.auth import establish_session, require_admin, require_csrf, verify_password
from somai_chat.admin.repository import ClientRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class LoginInput(BaseModel):
    username: str
    password: str


class ClientInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None


def _repository(request: Request) -> ClientRepository:
    return cast(ClientRepository, request.app.state.client_repository)


@router.post("/session")
async def login(request: Request, payload: LoginInput) -> dict[str, object]:
    settings = request.app.state.settings
    if settings is None or payload.username != settings.admin_username or not verify_password(
        payload.password, settings.admin_password.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": settings.admin_username, "csrf_token": establish_session(request, settings.admin_username)}


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> None:
    require_csrf(request)
    request.session.clear()


@router.get("/session")
async def session(request: Request) -> dict[str, str]:
    return {"username": require_admin(request), "csrf_token": request.session["csrf"]}


@router.get("/clients")
async def list_clients(request: Request) -> list[dict[str, object]]:
    require_admin(request)
    clients = await _repository(request).list()
    return [{"id": str(client.id), "name": client.name, "enabled": client.enabled} for client in clients]


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(request: Request, payload: ClientInput) -> dict[str, object]:
    require_csrf(request)
    client, key = await _repository(request).create(payload.name.strip(), payload.description, payload.expires_at)
    return {"id": str(client.id), "name": client.name, "key": key}


@router.post("/clients/{client_id}/enabled")
async def set_client_enabled(request: Request, client_id: UUID, enabled: bool) -> dict[str, bool]:
    require_csrf(request)
    if not await _repository(request).set_enabled(client_id, enabled):
        raise HTTPException(status_code=404, detail="Client not found")
    return {"enabled": enabled}


@router.post("/clients/{client_id}/keys/rotate")
async def rotate_key(request: Request, client_id: UUID, payload: ClientInput) -> dict[str, str]:
    require_csrf(request)
    key = await _repository(request).rotate(client_id, payload.expires_at)
    if key is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"key": key}
