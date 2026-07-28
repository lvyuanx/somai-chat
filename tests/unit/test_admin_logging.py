from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from starlette.requests import Request

from somai_chat.admin.presence import ClientPresenceRegistry
from somai_chat.api.admin import (
    ClientInput,
    KeyRotationInput,
    LoginInput,
    create_client,
    list_clients,
    login,
    reveal_key,
    rotate_key,
    set_client_enabled,
)
from somai_chat.api.capabilities import list_capabilities, reveal_capability_api_key, update_capability
from somai_chat.capabilities.models import CapabilityUpdate, CapabilityView
from somai_chat.core.config import Settings
from somai_chat.core.logging import configure_logging


class ClientRepositoryStub:
    def __init__(self) -> None:
        self.client_id = uuid4()

    async def list(self) -> list[object]:
        return [
            SimpleNamespace(
                id=self.client_id,
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
        ]

    async def create(self, name: str, description: str | None, expires_at: datetime | None) -> tuple[object, str]:
        del name, description, expires_at
        return SimpleNamespace(id=self.client_id, name="robot-a"), "somai_sk_abcdefgh12345678_secret"

    async def set_enabled(self, client_id: object, enabled: bool) -> bool:
        del client_id, enabled
        return True

    async def rotate(self, client_id: object, expires_at: datetime | None) -> str:
        del client_id, expires_at
        return "somai_sk_abcdefgh12345678_rotated"

    async def reveal_key(self, client_id: object) -> str:
        del client_id
        return "somai_sk_abcdefgh12345678_secret"


class CapabilityServiceStub:
    async def list_views(self) -> list[CapabilityView]:
        return [
            CapabilityView(
                key="weather",
                enabled=True,
                configuration={"api_host": "https://weather.example", "timeout_seconds": 5},
                api_key_masked="••••••••alue",
                can_reveal_api_key=True,
                updated_at=datetime(2026, 7, 27, tzinfo=UTC),
            )
        ]

    async def update(self, key: str, payload: CapabilityUpdate) -> CapabilityView:
        del key, payload
        return (await self.list_views())[0]

    async def reveal_api_key(self, key: str) -> str:
        del key
        return "secret-value"


def _request(
    *,
    repository: ClientRepositoryStub | None = None,
    presence: ClientPresenceRegistry | None = None,
    capability_service: CapabilityServiceStub | None = None,
    settings: Settings | None = None,
) -> Request:
    app = SimpleNamespace(
        state=SimpleNamespace(
            client_repository=repository or ClientRepositoryStub(),
            client_presence=presence or ClientPresenceRegistry(),
            capability_service=capability_service or CapabilityServiceStub(),
            settings=settings
            or Settings(
                _env_file=None,
                environment="test",
                openai_api_key="test-api-key",
                openai_model="test-model",
            ),
        )
    )
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [(b"x-csrf-token", b"token")],
            "session": {"admin": "admin", "csrf": "token"},
        }
    )


def _capture_logs(tmp_path) -> io.StringIO:
    stream = io.StringIO()
    configure_logging("INFO", log_dir=tmp_path / "logs", stream=stream)
    return stream


def test_admin_client_actions_emit_safe_project_logs(tmp_path) -> None:
    async def exercise() -> str:
        stream = _capture_logs(tmp_path)
        repository = ClientRepositoryStub()
        presence = ClientPresenceRegistry()
        request = _request(repository=repository, presence=presence)

        await list_clients(request)
        created = await create_client(request, ClientInput(name="robot-a"))
        await set_client_enabled(request, repository.client_id, enabled=False)
        await rotate_key(request, repository.client_id, payload=KeyRotationInput())
        await reveal_key(request, repository.client_id)

        log_text = stream.getvalue()
        assert "管理员查看客户端列表" in log_text
        assert "管理员创建客户端" in log_text
        assert "管理员修改客户端启用状态" in log_text
        assert "管理员轮换客户端 Key" in log_text
        assert "管理员查看客户端 Key" in log_text
        assert "客户端数=1" in log_text
        assert f"客户端ID={created['id']}" in log_text
        return log_text

    logs = asyncio.run(exercise())
    assert "somai_sk_" not in logs
    assert "secret" not in logs


def test_admin_login_and_capability_actions_emit_safe_project_logs(tmp_path) -> None:
    async def exercise() -> str:
        stream = _capture_logs(tmp_path)
        login_request = _request(capability_service=CapabilityServiceStub())
        capability_request = _request(capability_service=CapabilityServiceStub())

        await login(login_request, LoginInput(username="admin", password="123456"))
        await list_capabilities(capability_request)
        await update_capability(
            capability_request,
            "weather",
            CapabilityUpdate(enabled=True, configuration={"api_host": "https://weather.example"}),
        )
        await reveal_capability_api_key(capability_request, "weather")

        return stream.getvalue()

    logs = asyncio.run(exercise())
    assert "管理员登录成功" in logs
    assert "管理员查看能力列表" in logs
    assert "管理员更新能力" in logs
    assert "管理员查看能力 API Key" in logs
    assert "能力=天气" in logs
    assert "secret-value" not in logs
    assert "123456" not in logs
