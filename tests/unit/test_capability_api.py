from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from somai_chat.api.capabilities import list_capabilities, reveal_capability_api_key, update_capability
from somai_chat.capabilities.models import CapabilityUpdate, CapabilityView


class ServiceStub:
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


def request() -> Request:
    app = SimpleNamespace(state=SimpleNamespace(capability_service=ServiceStub()))
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [(b"x-csrf-token", b"token")],
            "session": {"admin": "admin", "csrf": "token"},
        }
    )


@pytest.mark.asyncio
async def test_list_capabilities_never_returns_plaintext() -> None:
    result = await list_capabilities(request())
    assert result[0]["api_key_masked"] == "••••••••alue"
    assert "secret-value" not in repr(result)


@pytest.mark.asyncio
async def test_update_and_reveal_require_csrf_and_return_safe_shapes() -> None:
    payload = CapabilityUpdate(
        enabled=True,
        configuration={"api_host": "https://weather.example", "timeout_seconds": 5},
    )
    updated = await update_capability(request(), "weather", payload)
    revealed = await reveal_capability_api_key(request(), "weather")

    assert updated["key"] == "weather"
    assert revealed == {"api_key": "secret-value"}
