import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from somai_chat.admin.presence import ClientPresenceRegistry
from somai_chat.api.admin import ClientInput, KeyRotationInput, create_client, list_clients, reveal_key


class ClientRepositoryStub:
    def __init__(self, clients: list[object]) -> None:
        self._clients = clients

    async def list(self) -> list[object]:
        return self._clients

    async def reveal_key(self, client_id: object) -> str | None:
        del client_id
        return "somai_sk_abcdefgh12345678_secret"


def test_client_list_includes_live_websocket_presence() -> None:
    async def exercise() -> None:
        client_id = uuid4()
        registry = ClientPresenceRegistry()

        async def close_connection() -> None:
            return None

        await registry.replace(client_id, "conn_live", close_connection)
        robot = SimpleNamespace(
            id=client_id,
            name="robot-a",
            description="现场机器人",
            enabled=True,
            last_authenticated_at=datetime(2026, 7, 19, tzinfo=UTC),
            access_keys=[
                SimpleNamespace(
                    key_id="abcdefgh12345678",
                    encrypted_key="encrypted-key",
                    created_at=datetime(2026, 7, 19, tzinfo=UTC),
                    revoked_at=None,
                )
            ],
        )
        app = SimpleNamespace(
            state=SimpleNamespace(
                client_repository=ClientRepositoryStub([robot]),
                client_presence=registry,
            )
        )
        request = Request(
            {
                "type": "http",
                "app": app,
                "headers": [],
                "session": {"admin": "admin"},
            }
        )

        result = await list_clients(request)

        assert result == [
            {
                "id": str(client_id),
                "name": "robot-a",
                "description": "现场机器人",
                "enabled": True,
                "online": True,
                "last_authenticated_at": datetime(2026, 7, 19, tzinfo=UTC),
                "key_masked": "somai_sk_abcd••••5678_••••••••",
                "can_reveal_key": True,
            }
        ]

    asyncio.run(exercise())


def test_revealing_a_key_requires_the_administrator_csrf_token() -> None:
    async def exercise() -> None:
        client_id = uuid4()
        app = SimpleNamespace(
            state=SimpleNamespace(
                client_repository=ClientRepositoryStub([]),
                client_presence=ClientPresenceRegistry(),
            )
        )
        request = Request(
            {
                "type": "http",
                "app": app,
                "headers": [(b"x-csrf-token", b"csrf-token")],
                "session": {"admin": "admin", "csrf": "csrf-token"},
            }
        )

        assert await reveal_key(request, client_id) == {"key": "somai_sk_abcdefgh12345678_secret"}

    asyncio.run(exercise())


def test_key_rotation_payload_allows_an_omitted_expiration() -> None:
    assert KeyRotationInput().expires_at is None


def test_duplicate_client_name_returns_a_conflict() -> None:
    class DuplicateClientRepository:
        async def create(self, name: str, description: str | None, expires_at: datetime | None) -> None:
            del name, description, expires_at
            raise IntegrityError("INSERT", {}, Exception("duplicate client name"))

    async def exercise() -> None:
        app = SimpleNamespace(
            state=SimpleNamespace(
                client_repository=DuplicateClientRepository(),
                client_presence=ClientPresenceRegistry(),
            )
        )
        request = Request(
            {
                "type": "http",
                "app": app,
                "headers": [(b"x-csrf-token", b"csrf-token")],
                "session": {"admin": "admin", "csrf": "csrf-token"},
            }
        )

        with pytest.raises(HTTPException) as captured:
            await create_client(request, ClientInput(name="duplicate"))

        assert captured.value.status_code == 409
        assert captured.value.detail == "Client name already exists"

    asyncio.run(exercise())
