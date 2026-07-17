# Agent 模块

## 模块简介

本模块负责 SOMAI 的稳定身份、LangGraph 会话状态和对话图装配。
模型供应商创建、协议解析和连接并发控制不属于本模块。

## 目录说明

- `prompts.py`：定义稳定身份、运行时能力说明及最终系统提示词。
- `state.py`：定义使用 `add_messages` 合并消息的 `ConversationState`。
- `graph.py`：构建最小对话图，并通过 `ConversationGraph` 提供安全异步访问。

## 核心接口

`build_conversation_graph(model, checkpointer=None, tools=())` 在无工具时创建 `START -> model -> END` 对话图；
传入工具时创建 `START -> model -> tools -> model` 条件循环，
并返回只公开 `ainvoke`、`astream` 和 `aget_state` 的 `ConversationGraph`。
调用方必须在 Graph 配置中传入非空 `thread_id`；
系统将 `conversation_id` 原样映射为该值。

## 主要流程与数据流

应用层把新用户消息写入 Graph。
Facade 在委托 LangGraph 前校验 `thread_id`，无效配置不会产生 Checkpoint。
它按 `thread_id` 锁定完整调用，同一会话的多轮调用串行执行，不同会话可并行。
模型节点临时在完整会话历史前加入一条 SOMAI 系统消息，异步调用模型，
并把返回的 AI 消息写回状态。若模型请求已注册工具，图进入 `ToolNode` 执行工具，并将工具结果作为消息回送模型；
否则结束本轮。
系统消息不写入 Checkpointer，因此不会随轮次持久化或重复累积。
一轮生成取消时，LangGraph 可能已保存本轮用户输入，
但未完成的 AI 流式片段不会作为完整消息写入状态。
应用层会同步关闭 Graph 流，因此同一 `thread_id` 的锁在取消返回前释放，
下一轮可以继续执行。

## 依赖关系与配置

模型通过 LangChain `BaseChatModel` 接口注入，本模块不依赖具体供应商。
默认使用 `InMemorySaver`，也允许测试或未来基础设施注入其他 Checkpointer。
会话锁与内存 Checkpointer 拥有相同的进程生命周期。
MVP 的状态和并发保护仅存在于单个进程内，进程重启后丢失，不支持多实例共享会话。

## 扩展方式与注意事项

当前运行时支持文本多轮对话和由组合根注入的受控工具。
未来接入视觉、设备或动作能力时，应扩展运行时能力清单和明确的工具节点，
不修改稳定人格，
也不得在未接入能力时声称已经感知或执行。
新增工具节点需保持消息状态和 `thread_id` 隔离语义，并补充真实图测试。
当前没有动作、ASR 或 TTS 节点；这些能力不得仅通过 Prompt 宣称存在。持久化扩展应替换
`build_conversation_graph` 的 Checkpointer 注入，同时把跨进程并发控制迁移到共享基础设施。
