"""Construction of the stateful SOMAI conversation graph."""

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from somai_chat.agent.prompts import SOMAI_SYSTEM_PROMPT
from somai_chat.agent.state import ConversationState


def build_conversation_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[ConversationState, None, ConversationState, ConversationState]:
    """Build the minimal stateful graph around an injected chat model."""

    async def invoke_model(state: ConversationState, config: RunnableConfig) -> ConversationState:
        thread_id = config.get("configurable", {}).get("thread_id")
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise ValueError("A non-empty configurable thread_id is required")

        response = await model.ainvoke([SystemMessage(content=SOMAI_SYSTEM_PROMPT), *state["messages"]], config=config)
        return {"messages": [response]}

    builder = StateGraph(ConversationState)
    builder.add_node("model", invoke_model)
    builder.add_edge(START, "model")
    builder.add_edge("model", END)
    saver = checkpointer if checkpointer is not None else InMemorySaver()
    return builder.compile(checkpointer=saver)
