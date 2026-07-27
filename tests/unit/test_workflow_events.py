from __future__ import annotations

from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool
from pydantic import PrivateAttr

from somai_chat.agent.graph import build_conversation_graph
from somai_chat.application.conversation import ConversationRuntime
from somai_chat.application.workflow import WorkflowEventTranslator, sanitize_workflow_payload
from somai_chat.device.tool import create_camera_capture_tool


class ToolCallingModel(BaseChatModel):
    _tools: list[BaseTool] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "workflow-test-model"

    def bind_tools(self, tools: list[BaseTool], **kwargs: Any) -> ToolCallingModel:
        del kwargs
        self._tools = tools
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        if any(isinstance(message, ToolMessage) for message in messages):
            response = AIMessage(content="查询完成。")
        else:
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "inspect_payload",
                        "args": {"api_key": "input-secret"},
                        "id": "inspect-call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=response)])


class CameraCallingModel(ToolCallingModel):
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        response = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "camera_capture",
                    "args": {"camera": "back", "reason": "查看桌面"},
                    "id": "camera-call",
                }
            ],
        )
        return ChatResult(generations=[ChatGeneration(message=response)])


@pytest.mark.asyncio
async def test_runtime_emits_ordered_workflow_nodes_with_safe_tool_payloads() -> None:
    @tool
    async def inspect_payload(api_key: str) -> dict[str, object]:
        """Return a diagnostic object used to exercise workflow payload safety."""
        assert api_key == "input-secret"
        return {
            "token": "output-secret",
            "nested": {"password": "nested-secret"},
            "blob": "x" * 13_000,
        }

    runtime = ConversationRuntime(build_conversation_graph(ToolCallingModel(), tools=[inspect_payload]))
    events = [
        event
        async for event in runtime.stream(
            "conv-workflow",
            "msg-workflow",
            "inspect",
            response_id="resp-workflow",
        )
    ]

    assert [event.type for event in events] == [
        "response.started",
        "workflow.node.started",
        "workflow.node.completed",
        "workflow.node.started",
        "workflow.node.completed",
        "workflow.node.started",
        "response.delta",
        "workflow.node.completed",
        "response.completed",
    ]
    node_starts = [event for event in events if event.type == "workflow.node.started"]
    assert [(event.data["kind"], event.data["name"]) for event in node_starts] == [
        ("model", "model"),
        ("tool", "inspect_payload"),
        ("model", "model"),
    ]
    assert node_starts[1].data["input"] == {"api_key": "[REDACTED]"}
    assert node_starts[1].data["input_truncated"] is False

    tool_completed = next(
        event
        for event in events
        if event.type == "workflow.node.completed" and event.data["node_id"] == node_starts[1].data["node_id"]
    )
    assert tool_completed.data["output_truncated"] is True
    assert "output-secret" not in str(tool_completed.data["output"])
    assert "nested-secret" not in str(tool_completed.data["output"])
    assert "[REDACTED]" in str(tool_completed.data["output"])
    assert len(str(tool_completed.data["output"])) <= 12_000
    assert all(int(event.data["duration_ms"]) >= 0 for event in events if "duration_ms" in event.data)
    assert next(event.data["delta"] for event in events if event.type == "response.delta") == "查询完成。"
    assert events[-1].data["content"] == "查询完成。"


def test_workflow_translator_correlates_parallel_nodes_and_hides_errors() -> None:
    ticks = iter((1.0, 1.1, 1.2, 1.4))
    translator = WorkflowEventTranslator("resp-parallel", clock=lambda: next(ticks))

    first_start = translator.translate(
        {"event": "on_tool_start", "run_id": "first", "name": "first_tool", "data": {"input": {}}}
    )
    second_start = translator.translate(
        {"event": "on_tool_start", "run_id": "second", "name": "second_tool", "data": {"input": {}}}
    )
    second_end = translator.translate(
        {"event": "on_tool_end", "run_id": "second", "name": "second_tool", "data": {"output": "ok"}}
    )
    first_error = translator.translate(
        {
            "event": "on_tool_error",
            "run_id": "first",
            "name": "first_tool",
            "data": {"error": RuntimeError("provider-secret-detail")},
        }
    )

    assert first_start is not None and second_start is not None
    assert second_end is not None and first_error is not None
    assert second_end.data == {
        "response_id": "resp-parallel",
        "node_id": second_start.data["node_id"],
        "duration_ms": 100,
        "output": "ok",
        "output_truncated": False,
    }
    assert first_error.type == "workflow.node.failed"
    assert first_error.data["node_id"] == first_start.data["node_id"]
    assert first_error.data["duration_ms"] == 400
    assert "provider-secret-detail" not in str(first_error.data)


def test_workflow_payload_replaces_non_scalar_unicode() -> None:
    payload, truncated = sanitize_workflow_payload({"value": "\ud800"})

    assert payload == {"value": "�"}
    assert truncated is True


@pytest.mark.asyncio
async def test_workflow_stream_preserves_camera_action_request() -> None:
    runtime = ConversationRuntime(build_conversation_graph(CameraCallingModel(), tools=[create_camera_capture_tool()]))

    events = [
        event
        async for event in runtime.stream(
            "conv-camera-workflow",
            "msg-camera-workflow",
            "看看桌面",
            response_id="resp-camera-workflow",
        )
    ]

    assert [event.type for event in events] == [
        "response.started",
        "workflow.node.started",
        "workflow.node.completed",
        "workflow.node.started",
        "workflow.node.completed",
        "action.request",
        "response.completed",
    ]
    assert events[-2].data["action"] == "camera.capture"
