import asyncio
from uuid import uuid4


def test_client_presence_replaces_an_existing_connection() -> None:
    from somai_chat.admin.presence import ClientPresenceRegistry

    async def exercise() -> None:
        registry = ClientPresenceRegistry()
        client_id = uuid4()

        assert not await registry.is_online(client_id)
        closed: list[str] = []

        async def close_first() -> None:
            closed.append("first")

        async def close_second() -> None:
            closed.append("second")

        assert await registry.replace(client_id, "conn_one", close_first) is None
        replaced = await registry.replace(client_id, "conn_two", close_second)
        assert replaced is not None
        await replaced.close()
        assert closed == ["first"]
        assert await registry.is_online(client_id)

        await registry.disconnect(client_id, "conn_one")
        assert await registry.is_online(client_id)
        await registry.disconnect(client_id, "conn_two")
        assert not await registry.is_online(client_id)

    asyncio.run(exercise())
