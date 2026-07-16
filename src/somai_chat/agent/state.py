"""Conversation state shared by the SOMAI graph nodes."""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ConversationState(TypedDict):
    """Message history persisted for one LangGraph thread."""

    messages: Annotated[list[AnyMessage], add_messages]
