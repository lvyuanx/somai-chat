"""Translate graph streams into protocol events and control one connection."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue

from somai_chat.agent.graph import ConversationGraph
from somai_chat.api.protocol import ServerEvent
from somai_chat.core.errors import ErrorCode, SomaiError

SendEvent = Callable[[ServerEvent], Awaitable[None]]


def _chunk_text(chunk: AIMessageChunk) -> str:
    content = chunk.content
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, Mapping):
            text = block.get("text")
            if block.get("type") == "text" and isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _usage(chunk: AIMessageChunk) -> dict[str, JsonValue] | None:
    if chunk.usage_metadata is None:
        return None
    return cast(dict[str, JsonValue], dict(chunk.usage_metadata))


class ConversationRuntime:
    """Run a graph turn and expose transport-neutral server events."""

    def __init__(self, graph: ConversationGraph) -> None:
        self._graph = graph

    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str | None = None,
    ) -> AsyncIterator[ServerEvent]:
        response_id = response_id or f"resp_{uuid4().hex}"
        yield ServerEvent.create(
            "response.started",
            {"response_id": response_id, "message_id": message_id},
        )
        complete_content: list[str] = []
        usage: dict[str, JsonValue] | None = None
        config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
        try:
            async for message, _metadata in self._graph.astream(
                {"messages": [HumanMessage(content=content)]},
                config=config,
                stream_mode="messages",
            ):
                if not isinstance(message, AIMessageChunk):
                    continue
                delta = _chunk_text(message)
                if delta:
                    complete_content.append(delta)
                    yield ServerEvent.create(
                        "response.delta",
                        {"response_id": response_id, "delta": delta},
                    )
                chunk_usage = _usage(message)
                if chunk_usage is not None:
                    usage = chunk_usage
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise SomaiError(
                ErrorCode.GENERATION_FAILED,
                "Unable to generate a response",
            ) from error

        yield ServerEvent.create(
            "response.completed",
            {
                "response_id": response_id,
                "content": "".join(complete_content),
                "usage": usage,
            },
        )


@dataclass
class _Generation:
    response_id: str
    message_id: str
    task: asyncio.Task[None] | None = None
    terminal_claimed: bool = False


class ConversationSession:
    """Own at most one generation task for a WebSocket connection."""

    def __init__(
        self,
        conversation_id: str,
        runtime: ConversationRuntime,
        send: SendEvent,
    ) -> None:
        self._conversation_id = conversation_id
        self._runtime = runtime
        self._send = send
        self._active: _Generation | None = None
        self._closed = False

    @property
    def active_response_id(self) -> str | None:
        return self._active.response_id if self._active is not None else None

    def start(self, message_id: str, content: str) -> str:
        if self._active is not None:
            raise SomaiError(
                ErrorCode.GENERATION_IN_PROGRESS,
                "A response is already being generated",
            )
        response_id = f"resp_{uuid4().hex}"
        generation = _Generation(response_id=response_id, message_id=message_id)
        self._active = generation
        generation.task = asyncio.create_task(self._pump(generation, content))
        return response_id

    async def cancel(self, response_id: str) -> None:
        generation = self._active
        if generation is None or generation.response_id != response_id or generation.task is None:
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")

        if generation.terminal_claimed:
            try:
                await generation.task
            except asyncio.CancelledError:
                pass
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")

        cancellation_requested = generation.task.cancel()
        if cancellation_requested:
            try:
                await generation.task
            except asyncio.CancelledError:
                pass
        if not cancellation_requested or generation.terminal_claimed:
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")
        if not self._closed:
            generation.terminal_claimed = True
            try:
                await self._send(
                    ServerEvent.create(
                        "response.cancelled",
                        {"response_id": response_id},
                    )
                )
            except Exception:
                return

    async def close(self) -> None:
        self._closed = True
        generation = self._active
        if generation is None or generation.task is None:
            return
        generation.task.cancel()
        try:
            await generation.task
        except asyncio.CancelledError:
            pass

    async def _pump(self, generation: _Generation, content: str) -> None:
        try:
            async for event in self._runtime.stream(
                self._conversation_id,
                generation.message_id,
                content,
                response_id=generation.response_id,
            ):
                if self._closed:
                    return
                if event.type in {"response.completed", "response.cancelled", "error"}:
                    generation.terminal_claimed = True
                try:
                    await self._send(event)
                except Exception:
                    return
        except asyncio.CancelledError:
            raise
        except SomaiError as error:
            await self._send_error(generation, error)
        except Exception:
            await self._send_error(
                generation,
                SomaiError(ErrorCode.GENERATION_FAILED, "Unable to generate a response"),
            )
        finally:
            if self._active is generation:
                self._active = None

    async def _send_error(self, generation: _Generation, error: SomaiError) -> None:
        if self._closed or generation.terminal_claimed:
            return
        generation.terminal_claimed = True
        event = ServerEvent.create(
            "error",
            {
                "code": error.code,
                "message": error.safe_message,
                "response_id": generation.response_id,
                "message_id": generation.message_id,
            },
        )
        try:
            await self._send(event)
        except Exception:
            return
