from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal, cast

import pytest
from langchain_core.messages import AIMessageChunk

from somai_chat.agent.graph import ConversationGraph
from somai_chat.api.protocol import ServerEvent
from somai_chat.application.conversation import ConversationRuntime, ConversationSession
from somai_chat.core.errors import ErrorCode, SomaiError

LIFECYCLE_REENTRY_MESSAGE = "Conversation lifecycle cannot be changed from the send callback"


class QuickRuntime:
    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        del conversation_id, content
        yield ServerEvent.create("response.started", {"response_id": response_id, "message_id": message_id})
        yield ServerEvent.create(
            "response.completed",
            {"response_id": response_id, "content": "done", "usage": None},
        )


class WaitingRuntime:
    def __init__(self, *, fail_cleanup: bool = False) -> None:
        self.closed = asyncio.Event()
        self.wait = asyncio.Event()
        self.fail_cleanup = fail_cleanup

    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        del conversation_id, content
        try:
            yield ServerEvent.create("response.started", {"response_id": response_id, "message_id": message_id})
            yield ServerEvent.create("response.delta", {"response_id": response_id, "delta": "partial"})
            await self.wait.wait()
        finally:
            self.closed.set()
            if self.fail_cleanup:
                raise RuntimeError("cleanup failed")


async def wait_until_idle(session: ConversationSession) -> None:
    for _ in range(100):
        if session.active_response_id is None:
            return
        await asyncio.sleep(0)
    raise AssertionError("session did not return to idle")


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type", ["response.started", "response.completed"])
@pytest.mark.parametrize("operation", ["cancel", "close"])
async def test_send_callback_cannot_reenter_active_lifecycle(
    event_type: str,
    operation: Literal["cancel", "close"],
) -> None:
    runtime = QuickRuntime()
    events: list[ServerEvent] = []
    reentry_errors: list[RuntimeError] = []
    response_id = ""
    session: ConversationSession

    async def send(event: ServerEvent) -> None:
        if event.type == event_type:
            try:
                if operation == "cancel":
                    await session.cancel(response_id)
                else:
                    await session.close()
            except RuntimeError as error:
                reentry_errors.append(error)
        events.append(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    response_id = session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert [str(error) for error in reentry_errors] == [LIFECYCLE_REENTRY_MESSAGE]
    assert [event.type for event in events] == ["response.started", "response.completed"]
    assert session.active_response_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "close"])
async def test_cancelled_send_owner_cannot_reenter_lifecycle(operation: Literal["cancel", "close"]) -> None:
    runtime = WaitingRuntime()
    events: list[ServerEvent] = []
    reentry_errors: list[RuntimeError] = []
    response_id = ""
    session: ConversationSession

    async def send(event: ServerEvent) -> None:
        if event.type == "response.cancelled":
            try:
                if operation == "cancel":
                    await session.cancel(response_id)
                else:
                    await session.close()
            except RuntimeError as error:
                reentry_errors.append(error)
        events.append(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)
    await session.cancel(response_id)

    assert [str(error) for error in reentry_errors] == [LIFECYCLE_REENTRY_MESSAGE]
    assert [event.type for event in events] == [
        "response.started",
        "response.delta",
        "response.cancelled",
    ]
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_uncaught_send_callback_reentry_stops_without_a_terminal_retry() -> None:
    runtime = QuickRuntime()
    attempts: list[str] = []
    session: ConversationSession

    async def send(event: ServerEvent) -> None:
        attempts.append(event.type)
        if event.type == "response.started":
            await session.close()

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert attempts == ["response.started"]
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_send_cancellation_is_not_replaced_by_runtime_cleanup_failure() -> None:
    runtime = WaitingRuntime(fail_cleanup=True)
    attempts: list[str] = []

    async def cancelled_send(event: ServerEvent) -> None:
        attempts.append(event.type)
        if event.type == "response.delta":
            raise asyncio.CancelledError

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), cancelled_send)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert attempts == ["response.started", "response.delta"]
    assert runtime.closed.is_set()


@pytest.mark.asyncio
async def test_external_cancel_wins_over_runtime_cleanup_failure() -> None:
    runtime = WaitingRuntime(fail_cleanup=True)
    delta_send_entered = asyncio.Event()
    hold_delta_send = asyncio.Event()
    events: list[ServerEvent] = []

    async def send(event: ServerEvent) -> None:
        if event.type == "response.delta":
            delta_send_entered.set()
            await hold_delta_send.wait()
        events.append(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    response_id = session.start("msg-1", "hello")
    await delta_send_entered.wait()

    await session.cancel(response_id)

    assert runtime.closed.is_set()
    assert [event.type for event in events] == ["response.started", "response.cancelled"]
    assert session.active_response_id is None


class CleanupFailingGraphStream:
    def __init__(self) -> None:
        self._yielded = False

    def __aiter__(self) -> CleanupFailingGraphStream:
        return self

    async def __anext__(self) -> tuple[AIMessageChunk, dict[str, Any]]:
        if self._yielded:
            raise StopAsyncIteration
        self._yielded = True
        return AIMessageChunk(content="done"), {}

    async def aclose(self) -> None:
        raise RuntimeError("cleanup failed")


class CleanupFailingGraph:
    def astream(self, *args: Any, **kwargs: Any) -> CleanupFailingGraphStream:
        del args, kwargs
        return CleanupFailingGraphStream()


class GatedCleanupRuntime:
    def __init__(self) -> None:
        self.cleanup_entered = asyncio.Event()
        self.release_cleanup = asyncio.Event()
        self.cleanup_done = asyncio.Event()
        self.pump_task: asyncio.Task[None] | None = None

    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        del conversation_id, content
        self.pump_task = asyncio.current_task()
        try:
            yield ServerEvent.create("response.started", {"response_id": response_id, "message_id": message_id})
            await asyncio.Event().wait()
        finally:
            self.cleanup_entered.set()
            await self.release_cleanup.wait()
            self.cleanup_done.set()


@pytest.mark.asyncio
async def test_cleanup_failure_without_primary_error_maps_to_one_safe_error() -> None:
    runtime = ConversationRuntime(cast(ConversationGraph, CleanupFailingGraph()))
    events: list[ServerEvent] = []

    async def send(event: ServerEvent) -> None:
        events.append(event)

    session = ConversationSession("conv-1", runtime, send)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert [event.type for event in events] == ["response.started", "response.delta", "error"]
    assert events[-1].data["code"] == ErrorCode.GENERATION_FAILED
    assert events[-1].data["message"] == "Unable to generate a response"


@pytest.mark.asyncio
async def test_close_does_not_recancel_pump_owned_by_cancel_cleanup() -> None:
    runtime = GatedCleanupRuntime()
    events: list[ServerEvent] = []

    async def send(event: ServerEvent) -> None:
        events.append(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)
    cancel_task = asyncio.create_task(session.cancel(response_id))
    await runtime.cleanup_entered.wait()
    close_task = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    runtime.release_cleanup.set()
    await close_task
    cancel_result = await asyncio.gather(cancel_task, return_exceptions=True)

    assert runtime.cleanup_done.is_set()
    assert runtime.pump_task is not None
    assert runtime.pump_task.cancelling() == 1
    assert isinstance(cancel_result[0], asyncio.CancelledError)
    assert [event.type for event in events] == ["response.started"]
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_concurrent_close_only_cancels_pump_once_and_both_wait_for_cleanup() -> None:
    runtime = GatedCleanupRuntime()

    async def send(event: ServerEvent) -> None:
        del event

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    session.start("msg-1", "hello")
    await asyncio.sleep(0)
    first_close = asyncio.create_task(session.close())
    await runtime.cleanup_entered.wait()
    second_close = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    assert runtime.pump_task is not None
    cancelling_before_release = runtime.pump_task.cancelling()
    runtime.release_cleanup.set()
    await asyncio.gather(first_close, second_close)

    assert cancelling_before_release == 1
    assert runtime.cleanup_done.is_set()
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_cancelling_one_close_waiter_does_not_cancel_pump_or_other_waiter() -> None:
    runtime = GatedCleanupRuntime()

    async def send(event: ServerEvent) -> None:
        del event

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    session.start("msg-1", "hello")
    await asyncio.sleep(0)
    surviving_close = asyncio.create_task(session.close())
    await runtime.cleanup_entered.wait()
    cancelled_close = asyncio.create_task(session.close())
    await asyncio.sleep(0)

    cancelled_close.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_close
    assert runtime.pump_task is not None
    assert runtime.pump_task.cancelling() == 1
    assert not runtime.pump_task.done()

    runtime.release_cleanup.set()
    await surviving_close

    assert runtime.cleanup_done.is_set()
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_cancel_cannot_take_ownership_after_close_started_pump_cleanup() -> None:
    runtime = GatedCleanupRuntime()
    events: list[ServerEvent] = []

    async def send(event: ServerEvent) -> None:
        events.append(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), send)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)
    close_task = asyncio.create_task(session.close())
    await runtime.cleanup_entered.wait()

    with pytest.raises(SomaiError) as captured:
        await session.cancel(response_id)

    assert captured.value.code is ErrorCode.CANCEL_NOT_FOUND
    assert runtime.pump_task is not None
    assert runtime.pump_task.cancelling() == 1
    runtime.release_cleanup.set()
    await close_task

    assert runtime.cleanup_done.is_set()
    assert [event.type for event in events] == ["response.started"]
    assert session.active_response_id is None
