"""Translate graph streams into protocol events and control one connection."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Mapping
from contextlib import aclosing
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.messages.ai import UsageMetadata, add_usage
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


def _usage_data(usage: UsageMetadata | None) -> dict[str, JsonValue] | None:
    if usage is None:
        return None
    return cast(dict[str, JsonValue], dict(usage))


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
        usage: UsageMetadata | None = None
        config: RunnableConfig = {"configurable": {"thread_id": conversation_id}}
        try:
            graph_stream = cast(
                AsyncGenerator[tuple[object, dict[str, object]], None],
                self._graph.astream(
                    {"messages": [HumanMessage(content=content)]},
                    config=config,
                    stream_mode="messages",
                ),
            )
            async with aclosing(graph_stream):
                async for message, _metadata in graph_stream:
                    if not isinstance(message, AIMessageChunk):
                        continue
                    delta = _chunk_text(message)
                    if delta:
                        complete_content.append(delta)
                        yield ServerEvent.create(
                            "response.delta",
                            {"response_id": response_id, "delta": delta},
                        )
                    if message.usage_metadata is not None:
                        usage = add_usage(usage, message.usage_metadata)
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
                "usage": _usage_data(usage),
            },
        )


@dataclass
class _Generation:
    response_id: str
    message_id: str
    task: asyncio.Task[None] | None = None
    cancellation_owner: asyncio.Task[None] | None = None
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
        if self._closed:
            raise SomaiError(ErrorCode.GENERATION_FAILED, "Conversation session is closed")
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
        if (
            generation is None
            or generation.response_id != response_id
            or generation.task is None
            or generation.cancellation_owner is not None
        ):
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")

        if generation.terminal_claimed:
            try:
                await generation.task
            except asyncio.CancelledError:
                pass
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")

        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("cancel must run in an asyncio task")
        generation.cancellation_owner = owner
        try:
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
        finally:
            if generation.cancellation_owner is owner:
                generation.cancellation_owner = None
            if self._active is generation:
                self._active = None

    async def close(self) -> None:
        self._closed = True
        generation = self._active
        if generation is None or generation.task is None:
            return
        current_task = asyncio.current_task()
        lifecycle_task = generation.cancellation_owner or generation.task
        if lifecycle_task is current_task:
            lifecycle_task = generation.task
        lifecycle_task.cancel()
        try:
            await lifecycle_task
        except asyncio.CancelledError:
            pass
        finally:
            if self._active is generation:
                self._active = None

    async def _pump(self, generation: _Generation, content: str) -> None:
        send_failed = False
        try:
            runtime_stream = cast(
                AsyncGenerator[ServerEvent, None],
                self._runtime.stream(
                    self._conversation_id,
                    generation.message_id,
                    content,
                    response_id=generation.response_id,
                ),
            )
            async with aclosing(runtime_stream):
                async for event in runtime_stream:
                    if self._closed:
                        return
                    if event.type in {"response.completed", "response.cancelled", "error"}:
                        generation.terminal_claimed = True
                    try:
                        await self._send(event)
                    except Exception:
                        send_failed = True
                        return
        except asyncio.CancelledError:
            raise
        except SomaiError as error:
            if not send_failed:
                await self._send_error(generation, error)
        except Exception:
            if not send_failed:
                await self._send_error(
                    generation,
                    SomaiError(ErrorCode.GENERATION_FAILED, "Unable to generate a response"),
                )
        finally:
            if self._active is generation and generation.cancellation_owner is None:
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
