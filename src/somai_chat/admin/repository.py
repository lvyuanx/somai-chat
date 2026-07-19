"""MySQL persistence operations for robot clients."""

from datetime import UTC, datetime
from uuid import UUID

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from somai_chat.admin.credentials import create_key_material, decrypt_key, encrypt_key, verify_key
from somai_chat.admin.models import Client, ClientAccessKey


class ClientRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], pepper: str, encryption_secret: str) -> None:
        self._sessions = sessions
        self._pepper = pepper
        self._encryption_secret = encryption_secret

    async def create(self, name: str, description: str | None, expires_at: datetime | None) -> tuple[Client, str]:
        key, material = create_key_material(self._pepper)
        async with self._sessions.begin() as session:
            client = Client(name=name, description=description)
            session.add(client)
            await session.flush()
            session.add(
                ClientAccessKey(
                    client_id=client.id,
                    key_id=material.key_id,
                    secret_digest=material.secret_digest,
                    encrypted_key=encrypt_key(key, self._encryption_secret),
                    expires_at=expires_at,
                )
            )
        return client, key

    async def list(self) -> list[Client]:
        async with self._sessions() as session:
            statement = select(Client).options(selectinload(Client.access_keys)).order_by(Client.created_at.desc())
            return list((await session.scalars(statement)).all())

    async def reveal_key(self, client_id: UUID) -> str | None:
        async with self._sessions() as session:
            statement = (
                select(ClientAccessKey)
                .where(ClientAccessKey.client_id == client_id, ClientAccessKey.revoked_at.is_(None))
                .order_by(ClientAccessKey.created_at.desc())
            )
            record = await session.scalar(statement)
            if record is None or record.encrypted_key is None:
                return None
            try:
                return decrypt_key(record.encrypted_key, self._encryption_secret)
            except InvalidToken:
                return None

    async def authenticate(self, key: str) -> Client | None:
        parts = key.split("_", 3)
        if len(parts) != 4:
            return None
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            record = await session.scalar(
                select(ClientAccessKey).where(ClientAccessKey.key_id == parts[2]).with_for_update()
            )
            if record is None or record.revoked_at is not None or (record.expires_at and record.expires_at <= now):
                return None
            client = await session.get(Client, record.client_id)
            verified = verify_key(key, record.key_id, record.secret_digest, self._pepper)
            if client is None or not client.enabled or not verified:
                return None
            record.last_used_at = now
            client.last_authenticated_at = now
            return client

    async def set_enabled(self, client_id: UUID, enabled: bool) -> bool:
        async with self._sessions.begin() as session:
            client = await session.get(Client, client_id, with_for_update=True)
            if client is None:
                return False
            client.enabled = enabled
            return True

    async def rotate(self, client_id: UUID, expires_at: datetime | None) -> str | None:
        key, material = create_key_material(self._pepper)
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            client = await session.get(Client, client_id, with_for_update=True)
            if client is None:
                return None
            keys = await session.scalars(
                select(ClientAccessKey).where(
                    ClientAccessKey.client_id == client_id,
                    ClientAccessKey.revoked_at.is_(None),
                )
            )
            for previous in keys:
                previous.revoked_at = now
            session.add(
                ClientAccessKey(
                    client_id=client_id,
                    key_id=material.key_id,
                    secret_digest=material.secret_digest,
                    encrypted_key=encrypt_key(key, self._encryption_secret),
                    expires_at=expires_at,
                )
            )
        return key
