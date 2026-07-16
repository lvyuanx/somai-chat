# Agent 模块

## 模块简介

本模块负责 SOMAI 的稳定身份、LangGraph 会话状态和对话图装配。
模型供应商创建、协议解析和连接并发控制不属于本模块。

## 目录说明

- `prompts.py`：定义稳定身份、运行时能力说明及最终系统提示词。
- `state.py`：定义使用 `add_messages` 合并消息的 `ConversationState`。
- `graph.py`：围绕注入的 `BaseChatModel` 构建并编译最小对话图。

## 核心接口

`build_conversation_graph(model, checkpointer=None)` 创建 `START -> model -> END` 对话图。
调用方必须在 Graph 配置中传入非空
`thread_id`；系统将 `conversation_id` 原样映射为该值。

## 主要流程与数据流

应用层把新用户消息写入 Graph。
模型节点临时在完整会话历史前加入一条 SOMAI 系统消息，异步调用模型，
并把返回的 AI 消息写回状态。
系统消息不写入 Checkpointer，因此不会随轮次持久化或重复累积。

## 依赖关系与配置

模型通过 LangChain `BaseChatModel` 接口注入，本模块不依赖具体供应商。
默认使用 `InMemorySaver`，也允许测试或未来基础设施注入其他 Checkpointer。
MVP 的状态仅存在于单个进程内，进程重启后丢失，不支持多实例共享会话。

## 扩展方式与注意事项

当前运行时能力只有文本多轮对话。
未来接入视觉、设备或动作能力时，应扩展运行时能力清单和明确的工具节点，
不修改稳定人格，
也不得在未接入能力时声称已经感知或执行。
新增工具节点需保持消息状态和 `thread_id` 隔离语义，并补充真实图测试。
