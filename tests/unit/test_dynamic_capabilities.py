from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import BaseTool, tool

from somai_chat.agent.graph import ConversationGraph, build_conversation_graph
from somai_chat.application.conversation import ConversationRuntime


@tool
async def first_tool() -> str:
    """Return the first marker."""
    return "first"


@tool
async def second_tool() -> str:
    """Return the second marker."""
    return "second"


class ChangingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> tuple[BaseTool, ...]:
        self.calls += 1
        return (first_tool,) if self.calls == 1 else (second_tool,)


class RecordingGraph:
    def __init__(self) -> None:
        self.names: list[tuple[str, ...]] = []

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        del args
        config = kwargs["config"]
        self.names.append(tuple(item.name for item in config["configurable"]["runtime_tools"]))
        yield AIMessageChunk(content="ok"), {}


@pytest.mark.asyncio
async def test_runtime_reads_one_tool_snapshot_per_turn() -> None:
    provider = ChangingProvider()
    graph = RecordingGraph()
    runtime = ConversationRuntime(cast(ConversationGraph, graph), tool_provider=provider)

    assert [event.type async for event in runtime.stream("conv", "msg-1", "first")][-1] == "response.completed"
    assert [event.type async for event in runtime.stream("conv", "msg-2", "second")][-1] == "response.completed"

    assert graph.names == [("first_tool",), ("second_tool",)]
    assert provider.calls == 2


def test_graph_accepts_dynamic_tools_without_static_managed_tools() -> None:
    class BindableModel:
        def bind_tools(self, tools: list[BaseTool]) -> "BindableModel":
            self.bound = {item.name for item in tools}
            return self

    model = BindableModel()

    graph = build_conversation_graph(cast(Any, model), dynamic_tools=True)

    assert graph is not None
