"""Translate graph streams into protocol events and control one connection."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import uuid4

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.messages.ai import UsageMetadata, add_usage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from pydantic import JsonValue

from somai_chat.agent.graph import ConversationGraph
from somai_chat.api.protocol import ServerEvent
from somai_chat.application.text_normalizer import TextNormalizer
from somai_chat.application.workflow import WorkflowEventTranslator
from somai_chat.core.errors import ErrorCode, SomaiError
from somai_chat.device.tool import parse_camera_capture_result
from somai_chat.vision.analyzer import ImageAnalyzer

SendEvent = Callable[[ServerEvent], Awaitable[None]]
ModelUnavailableClassifier = Callable[[BaseException], bool]
_LIFECYCLE_REENTRY_MESSAGE = "Conversation lifecycle cannot be changed from the send callback"


def _never_model_unavailable(error: BaseException) -> bool:
    del error
    return False


class _CloseableAsyncIterator[T](AsyncIterator[T], Protocol):
    async def aclose(self) -> None: ...


class ToolSnapshotProvider(Protocol):
    def snapshot(self) -> Sequence[BaseTool]: ...


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


def _message_text(message: AIMessage | AIMessageChunk) -> str:
    content = message.content
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

    def __init__(
        self,
        graph: ConversationGraph,
        model_unavailable_classifier: ModelUnavailableClassifier = _never_model_unavailable,
        image_analyzer: ImageAnalyzer | None = None,
        tool_provider: ToolSnapshotProvider | None = None,
    ) -> None:
        self._graph = graph
        self._model_unavailable_classifier = model_unavailable_classifier
        self._image_analyzer = image_analyzer
        self._tool_provider = tool_provider
        self._text_normalizer = TextNormalizer()

    async def stream(
        self,
        conversation_id: str,
        message_id: str,
        content: str,
        *,
        image_urls: Sequence[str] = (),
        response_id: str | None = None,
    ) -> AsyncIterator[ServerEvent]:
        response_id = response_id or f"resp_{uuid4().hex}"
        yield ServerEvent.create(
            "response.started",
            {"response_id": response_id, "message_id": message_id},
        )
        complete_content: list[str] = []
        usage: UsageMetadata | None = None
        camera_action: dict[str, str | int] | None = None
        runtime_tools = tuple(self._tool_provider.snapshot()) if self._tool_provider is not None else ()
        config: RunnableConfig = {"configurable": {"thread_id": conversation_id, "runtime_tools": runtime_tools}}
        try:
            enriched_content = content
            if image_urls:
                if self._image_analyzer is None:
                    raise SomaiError(ErrorCode.MODEL_UNAVAILABLE, "Model provider is unavailable")
                observation = await self._image_analyzer.analyze(content, image_urls)
                enriched_content = f"{content}\n\n{observation}"
            stream_events = getattr(self._graph, "astream_events", None)
            if callable(stream_events):
                workflow = WorkflowEventTranslator(response_id)
                streamed_model_runs: set[str] = set()
                graph_events = cast(
                    _CloseableAsyncIterator[dict[str, object]],
                    stream_events(
                        {"messages": [HumanMessage(content=enriched_content)]},
                        config=config,
                    ),
                )
                async with _managed_stream(graph_events):
                    async for graph_event in graph_events:
                        event_type = graph_event.get("event")
                        event_data = graph_event.get("data")
                        data = event_data if isinstance(event_data, Mapping) else {}
                        if isinstance(event_type, str) and event_type.endswith(("_start", "_error")):
                            workflow_event = workflow.translate(graph_event)
                            if workflow_event is not None:
                                yield workflow_event

                        message: AIMessage | AIMessageChunk | None = None
                        if event_type == "on_chat_model_stream":
                            streamed_model_runs.add(str(graph_event.get("run_id")))
                            chunk = data.get("chunk")
                            if isinstance(chunk, AIMessageChunk):
                                message = chunk
                        elif (
                            event_type == "on_chat_model_end"
                            and str(graph_event.get("run_id")) not in streamed_model_runs
                        ):
                            output = data.get("output")
                            if isinstance(output, AIMessage):
                                message = output
                        elif event_type == "on_tool_end" and camera_action is None:
                            output = data.get("output")
                            tool_content = output.content if isinstance(output, ToolMessage) else output
                            action = parse_camera_capture_result(tool_content)
                            if action is not None:
                                camera_action = action

                        if message is not None:
                            delta = self._text_normalizer.normalize_delta(_message_text(message))
                            if delta:
                                complete_content.append(delta)
                                yield ServerEvent.create(
                                    "response.delta",
                                    {"response_id": response_id, "delta": delta},
                                )
                            if message.usage_metadata is not None:
                                usage = add_usage(usage, message.usage_metadata)

                        if isinstance(event_type, str) and event_type.endswith("_end"):
                            workflow_event = workflow.translate(graph_event)
                            if workflow_event is not None:
                                yield workflow_event
            else:
                graph_stream = cast(
                    _CloseableAsyncIterator[tuple[object, dict[str, object]]],
                    self._graph.astream(
                        {"messages": [HumanMessage(content=enriched_content)]},
                        config=config,
                        stream_mode="messages",
                    ),
                )
                async with _managed_stream(graph_stream):
                    async for legacy_message, _metadata in graph_stream:
                        if isinstance(legacy_message, ToolMessage) and camera_action is None:
                            action = parse_camera_capture_result(legacy_message.content)
                            if action is not None:
                                camera_action = action
                        if not isinstance(legacy_message, AIMessageChunk):
                            continue
                        delta = self._text_normalizer.normalize_delta(_message_text(legacy_message))
                        if delta:
                            complete_content.append(delta)
                            yield ServerEvent.create(
                                "response.delta",
                                {"response_id": response_id, "delta": delta},
                            )
                        if legacy_message.usage_metadata is not None:
                            usage = add_usage(usage, legacy_message.usage_metadata)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            try:
                model_unavailable = self._model_unavailable_classifier(error)
            except BaseException:
                model_unavailable = False
            if model_unavailable:
                raise SomaiError(
                    ErrorCode.MODEL_UNAVAILABLE,
                    "Model provider is unavailable",
                ) from error
            raise SomaiError(
                ErrorCode.GENERATION_FAILED,
                "Unable to generate a response",
            ) from error

        if camera_action is not None:
            yield ServerEvent.create(
                "action.request",
                {
                    **camera_action,
                    "response_id": response_id,
                    "message_id": message_id,
                },
            )
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

    def start(self, message_id: str, content: str, image_urls: Sequence[str] = ()) -> str:
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
        generation.task = asyncio.create_task(self._pump(generation, content, image_urls))
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

    async def _pump(self, generation: _Generation, content: str, image_urls: Sequence[str]) -> None:
        try:
            if image_urls:
                stream = self._runtime.stream(
                    self._conversation_id,
                    generation.message_id,
                    content,
                    image_urls=image_urls,
                    response_id=generation.response_id,
                )
            else:
                stream = self._runtime.stream(
                    self._conversation_id,
                    generation.message_id,
                    content,
                    response_id=generation.response_id,
                )
            runtime_stream = cast(_CloseableAsyncIterator[ServerEvent], stream)
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
