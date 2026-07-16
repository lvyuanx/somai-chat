"""Translate graph streams into protocol events and control one connection."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import uuid4

import httpx
import openai
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_core.messages.ai import UsageMetadata, add_usage
from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue

from somai_chat.agent.graph import ConversationGraph
from somai_chat.api.protocol import ServerEvent
from somai_chat.core.errors import ErrorCode, SomaiError

SendEvent = Callable[[ServerEvent], Awaitable[None]]
_LIFECYCLE_REENTRY_MESSAGE = "Conversation lifecycle cannot be changed from the send callback"


class _CloseableAsyncIterator[T](AsyncIterator[T], Protocol):
    async def aclose(self) -> None: ...


@asynccontextmanager
async def _managed_stream[T](stream: _CloseableAsyncIterator[T]) -> AsyncIterator[_CloseableAsyncIterator[T]]:
    primary_error: BaseException | None = None
    try:
        yield stream
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            await stream.aclose()
        except BaseException:
            if primary_error is None:
                raise


class _SendFailed(Exception):
    """Stop a connection pump without attempting another send."""


async def _wait_for_task[T](task: asyncio.Task[T]) -> None:
    waiter = asyncio.current_task()
    initial_cancelling = waiter.cancelling() if waiter is not None else 0
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        waiter_was_cancelled = waiter is not None and waiter.cancelling() > initial_cancelling
        if waiter_was_cancelled or not task.cancelled():
            raise


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
                _CloseableAsyncIterator[tuple[object, dict[str, object]]],
                self._graph.astream(
                    {"messages": [HumanMessage(content=content)]},
                    config=config,
                    stream_mode="messages",
                ),
            )
            async with _managed_stream(graph_stream):
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
        except (openai.APIError, httpx.TransportError, httpx.TimeoutException) as error:
            raise SomaiError(
                ErrorCode.MODEL_UNAVAILABLE,
                "Model provider is unavailable",
            ) from error
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

    @staticmethod
    def _reject_lifecycle_reentry(generation: _Generation) -> None:
        current_task = asyncio.current_task()
        if current_task is generation.task or current_task is generation.cancellation_owner:
            raise RuntimeError(_LIFECYCLE_REENTRY_MESSAGE)

    async def cancel(self, response_id: str) -> None:
        generation = self._active
        if generation is not None:
            self._reject_lifecycle_reentry(generation)
        if (
            generation is None
            or generation.response_id != response_id
            or generation.task is None
            or generation.cancellation_owner is not None
            or self._closed
            or generation.task.cancelling() > 0
        ):
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")

        if generation.terminal_claimed:
            await _wait_for_task(generation.task)
            raise SomaiError(ErrorCode.CANCEL_NOT_FOUND, "Active response not found")

        owner = asyncio.current_task()
        if owner is None:
            raise RuntimeError("cancel must run in an asyncio task")
        generation.cancellation_owner = owner
        try:
            cancellation_requested = generation.task.cancel()
            if cancellation_requested:
                await _wait_for_task(generation.task)
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
            if self._active is generation and generation.task.done():
                self._active = None

    async def close(self) -> None:
        generation = self._active
        if generation is not None:
            self._reject_lifecycle_reentry(generation)
        self._closed = True
        if generation is None or generation.task is None:
            return
        cancellation_owner = generation.cancellation_owner
        if cancellation_owner is not None:
            if not cancellation_owner.done() and cancellation_owner.cancelling() == 0:
                cancellation_owner.cancel()
            await _wait_for_task(cancellation_owner)
            await _wait_for_task(generation.task)
        else:
            if not generation.task.done() and generation.task.cancelling() == 0:
                generation.task.cancel()
            await _wait_for_task(generation.task)
        if self._active is generation:
            self._active = None

    async def _pump(self, generation: _Generation, content: str) -> None:
        try:
            runtime_stream = cast(
                _CloseableAsyncIterator[ServerEvent],
                self._runtime.stream(
                    self._conversation_id,
                    generation.message_id,
                    content,
                    response_id=generation.response_id,
                ),
            )
            async with _managed_stream(runtime_stream):
                async for event in runtime_stream:
                    if self._closed:
                        return
                    if event.type in {"response.completed", "response.cancelled", "error"}:
                        generation.terminal_claimed = True
                    try:
                        await self._send(event)
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        raise _SendFailed from error
        except asyncio.CancelledError:
            raise
        except _SendFailed:
            return
        except SomaiError as error:
            await self._send_error(generation, error)
        except Exception:
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
