from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any, cast

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import PrivateAttr

from somai_chat.agent.graph import ConversationGraph, build_conversation_graph
from somai_chat.api.protocol import ServerEvent
from somai_chat.application.conversation import ConversationRuntime, ConversationSession
from somai_chat.core.errors import ErrorCode, SomaiError


class ObservableGraph:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.closed = asyncio.Event()
        self.release = asyncio.Event()

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        del args, kwargs
        async with self.lock:
            try:
                yield AIMessageChunk(content="chunk"), {}
                await self.release.wait()
            finally:
                self.closed.set()


class ObservableRuntime:
    def __init__(self) -> None:
        self.closed = asyncio.Event()
        self.release = asyncio.Event()

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
            yield ServerEvent.create("response.delta", {"response_id": response_id, "delta": "chunk"})
            await self.release.wait()
        finally:
            self.closed.set()


class FailingCloseRuntime(ObservableRuntime):
    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        try:
            async for event in super().stream(
                conversation_id,
                message_id,
                content,
                response_id=response_id,
            ):
                yield event
        finally:
            raise RuntimeError("close failed")


class UsageGraph:
    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        del args, kwargs
        yield (
            AIMessageChunk(
                content="first",
                usage_metadata={"input_tokens": 3, "output_tokens": 1, "total_tokens": 4},
            ),
            {},
        )
        yield (
            AIMessageChunk(
                content="second",
                usage_metadata={"input_tokens": 2, "output_tokens": 4, "total_tokens": 6},
            ),
            {},
        )


class RecordingSend:
    def __init__(self) -> None:
        self.events: list[ServerEvent] = []

    async def __call__(self, event: ServerEvent) -> None:
        self.events.append(event)


async def wait_until_idle(session: ConversationSession) -> None:
    for _ in range(100):
        if session.active_response_id is None:
            return
        await asyncio.sleep(0)
    raise AssertionError("session did not return to idle")


@pytest.mark.asyncio
async def test_runtime_aclose_closes_graph_stream_and_releases_lock_immediately() -> None:
    graph = ObservableGraph()
    stream = ConversationRuntime(cast(ConversationGraph, graph)).stream(
        "conv-1",
        "msg-1",
        "hello",
        response_id="resp-1",
    )
    assert (await anext(stream)).type == "response.started"
    assert (await anext(stream)).type == "response.delta"

    await stream.aclose()

    assert graph.closed.is_set()
    assert not graph.lock.locked()


@pytest.mark.asyncio
async def test_send_failure_closes_runtime_stream_before_session_becomes_idle() -> None:
    runtime = ObservableRuntime()
    send_calls = 0

    async def fail_on_delta(event: ServerEvent) -> None:
        nonlocal send_calls
        send_calls += 1
        if event.type == "response.delta":
            raise ConnectionError("socket closed")

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), fail_on_delta)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert send_calls == 2
    assert runtime.closed.is_set()


@pytest.mark.asyncio
async def test_send_failure_is_not_retried_when_runtime_close_also_fails() -> None:
    runtime = FailingCloseRuntime()
    send_calls = 0

    async def fail_on_delta(event: ServerEvent) -> None:
        nonlocal send_calls
        send_calls += 1
        if event.type == "response.delta":
            raise ConnectionError("socket closed")

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), fail_on_delta)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert send_calls == 2


@pytest.mark.asyncio
async def test_runtime_accumulates_usage_across_chunks() -> None:
    runtime = ConversationRuntime(cast(ConversationGraph, UsageGraph()))

    events = [event async for event in runtime.stream("conv-1", "msg-1", "hello", response_id="resp-usage")]

    assert events[-1].data["usage"] == {
        "input_tokens": 5,
        "output_tokens": 5,
        "total_tokens": 10,
    }


@pytest.mark.asyncio
async def test_start_rejects_a_closed_session_without_creating_a_response() -> None:
    runtime = ObservableRuntime()
    recorder = RecordingSend()
    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), recorder)
    await session.close()

    with pytest.raises(SomaiError) as captured:
        session.start("msg-1", "hello")

    assert captured.value.code is ErrorCode.GENERATION_FAILED
    assert captured.value.safe_message == "Conversation session is closed"
    assert session.active_response_id is None
    assert recorder.events == []


@pytest.mark.asyncio
async def test_cancelled_send_keeps_generation_busy_until_it_finishes() -> None:
    runtime = ObservableRuntime()
    cancelled_send_entered = asyncio.Event()
    release_cancelled_send = asyncio.Event()
    recorder = RecordingSend()

    async def blocking_send(event: ServerEvent) -> None:
        if event.type == "response.cancelled":
            cancelled_send_entered.set()
            await release_cancelled_send.wait()
        await recorder(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), blocking_send)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)
    cancel_task = asyncio.create_task(session.cancel(response_id))
    await cancelled_send_entered.wait()

    try:
        assert session.active_response_id == response_id
        with pytest.raises(SomaiError) as captured:
            session.start("msg-2", "again")
        assert captured.value.code is ErrorCode.GENERATION_IN_PROGRESS
    finally:
        release_cancelled_send.set()
        await cancel_task

    assert [event.type for event in recorder.events] == [
        "response.started",
        "response.delta",
        "response.cancelled",
    ]
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_close_cancels_and_waits_for_a_blocked_cancelled_send() -> None:
    runtime = ObservableRuntime()
    cancelled_send_entered = asyncio.Event()
    release_cancelled_send = asyncio.Event()
    recorder = RecordingSend()

    async def blocking_send(event: ServerEvent) -> None:
        if event.type == "response.cancelled":
            cancelled_send_entered.set()
            await release_cancelled_send.wait()
        await recorder(event)

    session = ConversationSession("conv-1", cast(ConversationRuntime, runtime), blocking_send)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)
    cancel_task = asyncio.create_task(session.cancel(response_id))
    await cancelled_send_entered.wait()

    await session.close()
    cancel_finished_when_close_returned = cancel_task.done()
    release_cancelled_send.set()
    with suppress(asyncio.CancelledError):
        await cancel_task

    assert cancel_finished_when_close_returned
    assert [event.type for event in recorder.events] == ["response.started", "response.delta"]
    assert session.active_response_id is None


class CancellableStreamingModel(BaseChatModel):
    _first_chunk: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _first_stream_closed: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _release_first: asyncio.Event = PrivateAttr(default_factory=asyncio.Event)
    _calls: int = PrivateAttr(default=0)

    @property
    def first_chunk(self) -> asyncio.Event:
        return self._first_chunk

    @property
    def first_stream_closed(self) -> asyncio.Event:
        return self._first_stream_closed

    @property
    def _llm_type(self) -> str:
        return "cancellable-streaming-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="complete"))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        self._calls += 1
        if self._calls == 1:
            try:
                yield ChatGenerationChunk(message=AIMessageChunk(content="partial"))
                self.first_chunk.set()
                await self._release_first.wait()
            finally:
                self.first_stream_closed.set()
            return
        yield ChatGenerationChunk(message=AIMessageChunk(content="complete"))


@pytest.mark.asyncio
async def test_real_graph_cancel_releases_lock_without_persisting_partial_ai() -> None:
    model = CancellableStreamingModel()
    graph = build_conversation_graph(model)
    runtime = ConversationRuntime(graph)
    recorder = RecordingSend()
    session = ConversationSession("conv-real", runtime, recorder)
    response_id = session.start("msg-1", "first")
    await model.first_chunk.wait()
    await asyncio.sleep(0)

    await session.cancel(response_id)

    assert model.first_stream_closed.is_set()
    assert "response.completed" not in [event.type for event in recorder.events]
    config = {"configurable": {"thread_id": "conv-real"}}
    state_after_cancel = await graph.aget_state(config)
    cancelled_messages = state_after_cancel.values.get("messages", [])
    assert [message.content for message in cancelled_messages] == ["first"]

    session.start("msg-2", "second")
    await wait_until_idle(session)
    final_state = await graph.aget_state(config)
    assert [message.content for message in final_state.values["messages"]] == ["first", "second", "complete"]
