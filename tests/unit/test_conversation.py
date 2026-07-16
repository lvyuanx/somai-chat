from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from somai_chat.agent.graph import ConversationGraph, build_conversation_graph
from somai_chat.api.protocol import ServerEvent
from somai_chat.application.conversation import ConversationRuntime, ConversationSession
from somai_chat.core.errors import ErrorCode, SomaiError


class StreamingChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "streaming-test-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="你好"))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        raise NotImplementedError

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        del messages, stop, run_manager, kwargs
        for text in ("你", "", "好"):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))


class ContentBlockGraph:
    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        del args, kwargs
        yield AIMessageChunk(content=[{"type": "text", "text": "内容"}]), {}
        yield AIMessageChunk(content=[{"type": "text", "text": "块"}]), {}


class FailingGraph:
    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        del args, kwargs
        raise RuntimeError("provider-secret-detail")
        yield AIMessageChunk(content="unreachable"), {}


class StubRuntime:
    def __init__(self, event_factory: Callable[[str, str], AsyncIterator[ServerEvent]]) -> None:
        self._event_factory = event_factory

    def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        response_id: str,
    ) -> AsyncIterator[ServerEvent]:
        del conversation_id, content
        return self._event_factory(response_id, message_id)


class EventRecorder:
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
async def test_runtime_streams_real_graph_chunks_in_order() -> None:
    runtime = ConversationRuntime(build_conversation_graph(StreamingChatModel()))

    events = [
        event
        async for event in runtime.stream(
            "conv-1",
            "msg-1",
            "你好",
            response_id="resp_fixed",
        )
    ]

    assert [event.type for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.completed",
    ]
    assert {event.data["response_id"] for event in events} == {"resp_fixed"}
    assert events[0].data["message_id"] == "msg-1"
    assert [event.data["delta"] for event in events[1:3]] == ["你", "好"]
    assert events[-1].data == {"response_id": "resp_fixed", "content": "你好", "usage": None}


@pytest.mark.asyncio
async def test_runtime_extracts_text_from_content_blocks() -> None:
    runtime = ConversationRuntime(cast(ConversationGraph, ContentBlockGraph()))

    events = [event async for event in runtime.stream("conv-1", "msg-1", "hello", response_id="resp_blocks")]

    assert [event.data["delta"] for event in events if event.type == "response.delta"] == ["内容", "块"]
    assert events[-1].data["content"] == "内容块"


@pytest.mark.asyncio
async def test_runtime_maps_graph_failure_without_leaking_details() -> None:
    runtime = ConversationRuntime(cast(ConversationGraph, FailingGraph()))

    with pytest.raises(SomaiError) as captured:
        async for _ in runtime.stream("conv-1", "msg-1", "hello", response_id="resp_fail"):
            pass

    assert captured.value.code is ErrorCode.GENERATION_FAILED
    assert captured.value.safe_message == "Unable to generate a response"
    assert "provider-secret-detail" not in str(captured.value)


@pytest.mark.asyncio
async def test_runtime_propagates_cancellation() -> None:
    cancelled = asyncio.CancelledError()

    class CancelledGraph:
        async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
            del args, kwargs
            raise cancelled
            yield AIMessageChunk(content="unreachable"), {}

    runtime = ConversationRuntime(cast(ConversationGraph, CancelledGraph()))
    with pytest.raises(asyncio.CancelledError) as captured:
        async for _ in runtime.stream("conv-1", "msg-1", "hello", response_id="resp_cancel"):
            pass
    assert captured.value is cancelled


def controlled_events(
    gate: asyncio.Event,
    *,
    fail: SomaiError | None = None,
) -> Callable[[str, str], AsyncIterator[ServerEvent]]:
    async def events(response_id: str, message_id: str) -> AsyncIterator[ServerEvent]:
        yield ServerEvent.create("response.started", {"response_id": response_id, "message_id": message_id})
        await gate.wait()
        if fail is not None:
            raise fail
        yield ServerEvent.create(
            "response.completed",
            {"response_id": response_id, "content": "done", "usage": None},
        )

    return events


@pytest.mark.asyncio
async def test_session_rejects_start_while_generation_is_active() -> None:
    gate = asyncio.Event()
    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate)), recorder)

    response_id = session.start("msg-1", "hello")
    with pytest.raises(SomaiError) as captured:
        session.start("msg-2", "again")

    assert response_id.startswith("resp_")
    assert captured.value.code is ErrorCode.GENERATION_IN_PROGRESS
    await session.close()


@pytest.mark.asyncio
async def test_session_cancels_matching_response_and_can_continue() -> None:
    first_gate = asyncio.Event()
    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(first_gate)), recorder)
    first_response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)

    await session.cancel(first_response_id)

    assert [event.type for event in recorder.events] == ["response.started", "response.cancelled"]
    assert recorder.events[-1].data["response_id"] == first_response_id
    second_response_id = session.start("msg-2", "again")
    assert second_response_id != first_response_id
    await session.close()


@pytest.mark.asyncio
async def test_session_rejects_unknown_cancel_id() -> None:
    gate = asyncio.Event()
    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate)), recorder)
    active_id = session.start("msg-1", "hello")

    with pytest.raises(SomaiError) as captured:
        await session.cancel("resp_unknown")

    assert captured.value.code is ErrorCode.CANCEL_NOT_FOUND
    assert session.active_response_id == active_id
    await session.close()


@pytest.mark.asyncio
async def test_session_close_cancels_without_terminal_event() -> None:
    gate = asyncio.Event()
    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate)), recorder)
    session.start("msg-1", "hello")
    await asyncio.sleep(0)

    await session.close()

    assert [event.type for event in recorder.events] == ["response.started"]
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_runtime_failure_sends_one_safe_error_and_returns_idle() -> None:
    gate = asyncio.Event()
    failure = SomaiError(ErrorCode.GENERATION_FAILED, "Unable to generate a response")
    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate, fail=failure)), recorder)
    response_id = session.start("msg-1", "secret input")
    gate.set()
    await wait_until_idle(session)

    errors = [event for event in recorder.events if event.type == "error"]
    assert len(errors) == 1
    assert errors[0].data == {
        "code": "GENERATION_FAILED",
        "message": "Unable to generate a response",
        "response_id": response_id,
        "message_id": "msg-1",
    }


@pytest.mark.asyncio
async def test_unexpected_runtime_failure_is_also_safe() -> None:
    async def events(response_id: str, message_id: str) -> AsyncIterator[ServerEvent]:
        del response_id, message_id
        raise RuntimeError("internal-secret")
        yield ServerEvent.create("unreachable", {})

    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(events), recorder)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert len(recorder.events) == 1
    assert recorder.events[0].type == "error"
    assert recorder.events[0].data["code"] == "GENERATION_FAILED"
    assert "internal-secret" not in str(recorder.events[0].data)


@pytest.mark.asyncio
async def test_send_failure_stops_pump_without_another_send() -> None:
    calls = 0

    async def failing_send(event: ServerEvent) -> None:
        nonlocal calls
        del event
        calls += 1
        raise ConnectionError("socket closed")

    gate = asyncio.Event()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate)), failing_send)
    session.start("msg-1", "hello")
    await wait_until_idle(session)

    assert calls == 1


@pytest.mark.asyncio
async def test_cancel_send_failure_is_swallowed_without_retry() -> None:
    calls = 0

    async def send(event: ServerEvent) -> None:
        nonlocal calls
        calls += 1
        if event.type == "response.cancelled":
            raise ConnectionError("socket closed")

    gate = asyncio.Event()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate)), send)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)

    await session.cancel(response_id)

    assert calls == 2
    assert session.active_response_id is None


@pytest.mark.asyncio
async def test_fast_completion_cancel_race_has_at_most_one_terminal_event() -> None:
    gate = asyncio.Event()
    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(controlled_events(gate)), recorder)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)

    gate.set()
    try:
        await session.cancel(response_id)
    except SomaiError as error:
        assert error.code is ErrorCode.CANCEL_NOT_FOUND
    await wait_until_idle(session)

    terminal = [
        event for event in recorder.events if event.type in {"response.completed", "response.cancelled", "error"}
    ]
    assert len(terminal) == 1


@pytest.mark.asyncio
async def test_cancelled_partial_response_never_completes() -> None:
    gate = asyncio.Event()

    async def events(response_id: str, message_id: str) -> AsyncIterator[ServerEvent]:
        yield ServerEvent.create("response.started", {"response_id": response_id, "message_id": message_id})
        yield ServerEvent.create("response.delta", {"response_id": response_id, "delta": "partial"})
        await gate.wait()
        yield ServerEvent.create(
            "response.completed",
            {"response_id": response_id, "content": "partial done", "usage": None},
        )

    recorder = EventRecorder()
    session = ConversationSession("conv-1", StubRuntime(events), recorder)
    response_id = session.start("msg-1", "hello")
    await asyncio.sleep(0)

    await session.cancel(response_id)

    assert [event.type for event in recorder.events] == [
        "response.started",
        "response.delta",
        "response.cancelled",
    ]
