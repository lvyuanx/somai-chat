from __future__ import annotations

import asyncio
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
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


class ConcurrencyTrackingChatModel(RecordingChatModel):
    _active_calls: int = PrivateAttr(default=0)
    _max_active_calls: int = PrivateAttr(default=0)

    @property
    def max_active_calls(self) -> int:
        return self._max_active_calls

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self._active_calls += 1
        self._max_active_calls = max(self._max_active_calls, self._active_calls)
        try:
            await asyncio.sleep(0.03)
            return self._generate(messages)
        finally:
            self._active_calls -= 1


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
    await injected_graph.ainvoke(user_input("注入"), config=graph_config("injected-thread"))

    assert len([checkpoint async for checkpoint in injected_checkpointer.alist(None)]) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [None, {}, {"configurable": {}}, graph_config(""), graph_config("   ")])
async def test_rejects_missing_or_empty_thread_id(config: RunnableConfig | None) -> None:
    graph = build_conversation_graph(RecordingChatModel())

    with pytest.raises(ValueError, match="thread_id"):
        await graph.ainvoke(user_input("你好"), config=config)


@pytest.mark.asyncio
async def test_invalid_thread_id_does_not_create_a_checkpoint() -> None:
    checkpointer = InMemorySaver()
    graph = build_conversation_graph(RecordingChatModel(), checkpointer=checkpointer)
    invalid_config = graph_config("   ")

    with pytest.raises(ValueError, match="thread_id"):
        await graph.ainvoke(user_input("不应保存"), config=invalid_config)
    with pytest.raises(ValueError, match="thread_id"):
        async for _ in graph.astream(user_input("不应保存"), config=invalid_config):
            pass
    with pytest.raises(ValueError, match="thread_id"):
        await graph.aget_state(invalid_config)

    assert [checkpoint async for checkpoint in checkpointer.alist(None)] == []


@pytest.mark.asyncio
async def test_same_thread_concurrent_invocations_are_serialized_without_lost_messages() -> None:
    model = ConcurrencyTrackingChatModel()
    graph = build_conversation_graph(model)
    config = graph_config("conversation-a")

    results = await asyncio.gather(
        graph.ainvoke(user_input("A消息"), config=config),
        graph.ainvoke(user_input("B消息"), config=config),
    )

    state = await graph.aget_state(config)
    contents = [message.content for message in state.values["messages"]]
    assert model.max_active_calls == 1
    assert sorted(tuple(contents[index : index + 2]) for index in range(0, len(contents), 2)) == [
        ("A消息", "回复：A消息"),
        ("B消息", "回复：B消息"),
    ]
    assert [result["messages"][-1].content for result in results] == ["回复：A消息", "回复：B消息"]


@pytest.mark.asyncio
async def test_concurrent_threads_do_not_mix_history() -> None:
    model = ConcurrencyTrackingChatModel()
    graph = build_conversation_graph(model)

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
    assert model.max_active_calls > 1
