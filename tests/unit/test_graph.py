from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from somai_chat.agent.graph import build_conversation_graph
from somai_chat.agent.prompts import SOMAI_SYSTEM_PROMPT
from somai_chat.agent.state import ConversationState


class RecordingChatModel(BaseChatModel):
    _calls: list[list[BaseMessage]] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "recording-chat-model"

    @property
    def calls(self) -> list[list[BaseMessage]]:
        return self._calls

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self._calls.append(list(messages))
        latest_user_message = next(message for message in reversed(messages) if isinstance(message, HumanMessage))
        reply = AIMessage(content=f"回复：{latest_user_message.content}")
        return ChatResult(generations=[ChatGeneration(message=reply)])


def graph_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def user_input(content: str) -> ConversationState:
    return {"messages": [HumanMessage(content=content)]}


@pytest.mark.asyncio
async def test_single_turn_persists_user_and_assistant_messages() -> None:
    graph = build_conversation_graph(RecordingChatModel())
    config = graph_config("conversation-a")

    await graph.ainvoke(user_input("你好"), config=config)
    state = await graph.aget_state(config)

    assert [message.content for message in state.values["messages"]] == ["你好", "回复：你好"]


@pytest.mark.asyncio
async def test_same_thread_retains_ordered_multi_turn_history() -> None:
    model = RecordingChatModel()
    graph = build_conversation_graph(model)
    config = graph_config("conversation-a")

    await graph.ainvoke(user_input("第一轮"), config=config)
    await graph.ainvoke(user_input("第二轮"), config=config)

    state = await graph.aget_state(config)
    assert [message.content for message in state.values["messages"]] == [
        "第一轮",
        "回复：第一轮",
        "第二轮",
        "回复：第二轮",
    ]
    assert [message.content for message in model.calls[1]][1:] == ["第一轮", "回复：第一轮", "第二轮"]


@pytest.mark.asyncio
async def test_different_threads_are_isolated() -> None:
    graph = build_conversation_graph(RecordingChatModel())

    await graph.ainvoke(user_input("A消息"), config=graph_config("conversation-a"))
    await graph.ainvoke(user_input("B消息"), config=graph_config("conversation-b"))

    state_b = await graph.aget_state(graph_config("conversation-b"))
    assert [message.content for message in state_b.values["messages"]] == ["B消息", "回复：B消息"]


@pytest.mark.asyncio
async def test_system_prompt_is_sent_each_turn_without_being_persisted() -> None:
    model = RecordingChatModel()
    graph = build_conversation_graph(model)
    config = graph_config("conversation-a")

    await graph.ainvoke(user_input("第一轮"), config=config)
    await graph.ainvoke(user_input("第二轮"), config=config)

    assert len(model.calls) == 2
    for call in model.calls:
        system_messages = [message for message in call if isinstance(message, SystemMessage)]
        assert [message.content for message in system_messages] == [SOMAI_SYSTEM_PROMPT]

    state = await graph.aget_state(config)
    assert not any(isinstance(message, SystemMessage) for message in state.values["messages"])


@pytest.mark.asyncio
async def test_uses_default_and_injected_checkpointers() -> None:
    default_graph = build_conversation_graph(RecordingChatModel())
    injected_checkpointer = InMemorySaver()
    injected_graph = build_conversation_graph(RecordingChatModel(), checkpointer=injected_checkpointer)

    await default_graph.ainvoke(user_input("默认"), config=graph_config("default-thread"))

    assert isinstance(default_graph.checkpointer, InMemorySaver)
    assert injected_graph.checkpointer is injected_checkpointer


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [None, graph_config("")])
async def test_rejects_missing_or_empty_thread_id(config: RunnableConfig | None) -> None:
    graph = build_conversation_graph(RecordingChatModel())

    with pytest.raises(ValueError, match="thread_id"):
        await graph.ainvoke(user_input("你好"), config=config)


@pytest.mark.asyncio
async def test_concurrent_threads_do_not_mix_history() -> None:
    graph = build_conversation_graph(RecordingChatModel())

    await asyncio.gather(
        graph.ainvoke(user_input("A消息"), config=graph_config("conversation-a")),
        graph.ainvoke(user_input("B消息"), config=graph_config("conversation-b")),
    )

    state_a, state_b = await asyncio.gather(
        graph.aget_state(graph_config("conversation-a")),
        graph.aget_state(graph_config("conversation-b")),
    )
    assert [message.content for message in state_a.values["messages"]] == ["A消息", "回复：A消息"]
    assert [message.content for message in state_b.values["messages"]] == ["B消息", "回复：B消息"]
