"""In-memory presence for currently connected robot clients."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ActiveClientConnection:
    connection_id: str
    close: Callable[[], Awaitable[None]]


class ClientPresenceRegistry:
    """Tracks the one active WebSocket connection allowed for each client."""

    def __init__(self) -> None:
        self._connections: dict[UUID, ActiveClientConnection] = {}
        self._lock = asyncio.Lock()

    async def replace(
        self,
        client_id: UUID,
        connection_id: str,
        close: Callable[[], Awaitable[None]],
    ) -> ActiveClientConnection | None:
        async with self._lock:
            previous = self._connections.get(client_id)
            self._connections[client_id] = ActiveClientConnection(connection_id, close)
            return previous

    async def disconnect(self, client_id: UUID, connection_id: str) -> None:
        async with self._lock:
            active_connection = self._connections.get(client_id)
            if active_connection is None or active_connection.connection_id != connection_id:
                return
            del self._connections[client_id]

    async def online_client_ids(self) -> frozenset[UUID]:
        async with self._lock:
            return frozenset(self._connections)

    async def is_online(self, client_id: UUID) -> bool:
        async with self._lock:
            return client_id in self._connections
