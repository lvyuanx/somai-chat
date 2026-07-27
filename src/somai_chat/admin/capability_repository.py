"""Persistence operations for managed capabilities."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from somai_chat.admin.models import Capability
from somai_chat.capabilities.models import CapabilityKey, StoredCapability


class CapabilityRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    def _stored(row: Capability) -> StoredCapability:
        return StoredCapability(
            key=cast(CapabilityKey, row.key),
            enabled=row.enabled,
            configuration=cast(dict[str, JsonValue], dict(row.configuration)),
            encrypted_api_key=row.encrypted_api_key,
            updated_at=row.updated_at,
        )

    async def seed_missing(self, seeds: Sequence[StoredCapability]) -> None:
        async with self._sessions.begin() as session:
            existing = set(await session.scalars(select(Capability.key)))
            session.add_all(
                Capability(
                    key=seed.key,
                    enabled=seed.enabled,
                    configuration=dict(seed.configuration),
                    encrypted_api_key=seed.encrypted_api_key,
                )
                for seed in seeds
                if seed.key not in existing
            )

    async def list(self) -> list[StoredCapability]:
        async with self._sessions() as session:
            rows = await session.scalars(select(Capability).order_by(Capability.key))
            return [self._stored(row) for row in rows]

    async def update(self, value: StoredCapability) -> StoredCapability | None:
        async with self._sessions.begin() as session:
            row = await session.scalar(select(Capability).where(Capability.key == value.key).with_for_update())
            if row is None:
                return None
            row.enabled = value.enabled
            row.configuration = dict(value.configuration)
            row.encrypted_api_key = value.encrypted_api_key
            await session.flush()
            await session.refresh(row)
            return self._stored(row)


class MemoryCapabilityRepository:
    """Test-environment storage used when the real server is exercised without MySQL."""

    def __init__(self) -> None:
        self._values: dict[CapabilityKey, StoredCapability] = {}

    async def seed_missing(self, seeds: Sequence[StoredCapability]) -> None:
        for seed in seeds:
            self._values.setdefault(seed.key, replace(seed, updated_at=datetime.now(UTC)))

    async def list(self) -> list[StoredCapability]:
        return sorted(self._values.values(), key=lambda item: item.key)

    async def update(self, value: StoredCapability) -> StoredCapability | None:
        if value.key not in self._values:
            return None
        saved = replace(value, updated_at=datetime.now(UTC))
        self._values[value.key] = saved
        return saved
