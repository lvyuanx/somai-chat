"""Construction and safe access facade for the SOMAI conversation graph."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, cast

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import StateSnapshot

from somai_chat.agent.prompts import SOMAI_SYSTEM_PROMPT
from somai_chat.agent.state import ConversationState
from somai_chat.device.tool import parse_camera_capture_result

CompiledConversationGraph = CompiledStateGraph[ConversationState, None, ConversationState, ConversationState]
MessageStreamItem = tuple[AnyMessage, dict[str, Any]]
GraphStreamEvent = dict[str, Any]


class ConversationGraph:
    """Validate and serialize access to a compiled in-memory conversation graph."""

    def __init__(self, graph: CompiledConversationGraph) -> None:
        self._graph = graph
        self._thread_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _thread_id(config: RunnableConfig | None) -> str:
        configurable = config.get("configurable") if config is not None else None
        thread_id = configurable.get("thread_id") if configurable is not None else None
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("A non-empty configurable thread_id is required")
        return thread_id

    def _thread_lock(self, thread_id: str) -> asyncio.Lock:
        lock = self._thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[thread_id] = lock
        return lock

    async def ainvoke(
        self,
        input: ConversationState,
        config: RunnableConfig | None = None,
    ) -> ConversationState:
        """Run one complete turn after validating and locking its thread."""
        thread_id = self._thread_id(config)
        async with self._thread_lock(thread_id):
            result = await self._graph.ainvoke(input, config=config)
        return cast(ConversationState, result)

    async def astream(
        self,
        input: ConversationState,
        config: RunnableConfig | None = None,
        *,
        stream_mode: Literal["messages"] = "messages",
    ) -> AsyncIterator[MessageStreamItem]:
        """Stream one complete turn while holding its thread lock."""
        thread_id = self._thread_id(config)
        async with self._thread_lock(thread_id):
            async for item in self._graph.astream(input, config=config, stream_mode=stream_mode):
                yield cast(MessageStreamItem, item)

    async def astream_events(
        self,
        input: ConversationState,
        config: RunnableConfig | None = None,
    ) -> AsyncIterator[GraphStreamEvent]:
        """Stream model and tool lifecycle events while holding the thread lock."""
        thread_id = self._thread_id(config)
        async with self._thread_lock(thread_id):
            stream = cast(
                AsyncIterator[GraphStreamEvent],
                self._graph.astream_events(input, config=config, version="v2"),
            )
            async for item in stream:
                yield item

    async def aget_state(self, config: RunnableConfig) -> StateSnapshot:
        """Read a valid thread state without racing an active turn."""
        thread_id = self._thread_id(config)
        async with self._thread_lock(thread_id):
            return await self._graph.aget_state(config)


def build_conversation_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    tools: Sequence[BaseTool] = (),
    dynamic_tools: bool = False,
) -> ConversationGraph:
    """Build the minimal stateful graph around an injected chat model."""

    def selected_tools(config: RunnableConfig) -> tuple[BaseTool, ...]:
        configurable = config.get("configurable", {})
        runtime_tools = configurable.get("runtime_tools", ()) if dynamic_tools else ()
        if not isinstance(runtime_tools, Sequence) or not all(isinstance(item, BaseTool) for item in runtime_tools):
            raise ValueError("runtime_tools must contain tools")
        return (*tools, *cast(Sequence[BaseTool], runtime_tools))

    async def invoke_model(state: ConversationState, config: RunnableConfig) -> ConversationState:
        turn_tools = selected_tools(config)
        bound_model = model.bind_tools(list(turn_tools)) if turn_tools else model
        response = await bound_model.ainvoke(
            [SystemMessage(content=SOMAI_SYSTEM_PROMPT), *state["messages"]],
            config=config,
        )
        return {"messages": [response]}

    async def invoke_tools(state: ConversationState, config: RunnableConfig) -> ConversationState:
        node = ToolNode(list(selected_tools(config)))
        return cast(ConversationState, await node.ainvoke(state, config=config))

    def route_after_tools(state: ConversationState) -> Literal["model", "end"]:
        last_message = state["messages"][-1] if state["messages"] else None
        if isinstance(last_message, ToolMessage) and parse_camera_capture_result(last_message.content) is not None:
            return "end"
        return "model"

    builder = StateGraph(ConversationState)
    builder.add_node("model", invoke_model)
    builder.add_edge(START, "model")
    if tools or dynamic_tools:
        builder.add_node("tools", invoke_tools)
        builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
        builder.add_conditional_edges("tools", route_after_tools, {"model": "model", "end": END})
    else:
        builder.add_edge("model", END)
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    return ConversationGraph(builder.compile(checkpointer=saver))
