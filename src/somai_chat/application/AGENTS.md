# Application 模块

## 模块简介

`application` 编排一轮 LangGraph 对话，并管理单个客户端连接的生成生命周期。
它不解析传输协议，也不创建模型供应商客户端。

## 主要职责

- 把用户文本和 `conversation_id` 交给 Conversation Graph。
- 将模型消息流转换为稳定的服务端 started、delta、completed 事件。
- 确保每个连接同一时间只有一个生成任务，并支持精确取消和安全关闭。
- 将生成异常映射为单个安全 error 事件，避免暴露供应商内部信息。

## 目录说明与核心类

- `conversation.py`：包含 `ConversationRuntime` 与 `ConversationSession`。
- `__init__.py`：包标识，不创建运行时全局单例。

`ConversationRuntime` 负责一轮生成和事件翻译；
`ConversationSession` 是每个 WebSocket 连接独有的控制器。

## 核心接口与主要流程

`ConversationRuntime.stream(conversation_id, message_id, content, response_id=...)` 把会话标识映射为
LangGraph `thread_id`，过滤空的 AI 文本块，拼接最终文本并携带可用 usage。

`ConversationSession.start()` 同步返回本轮 `response_id` 并在后台泵送事件；
活跃时再次调用会返回稳定忙碌错误。
`cancel()` 只取消匹配的活跃响应，等待任务停止后发送一次 cancelled；
`close()` 停止任务且不发送终态。
若 completed 或 error 已取得终态发送权，`cancel()` 等待该发送结束并返回 `CANCEL_NOT_FOUND`，
不得中断已经开始的终态发送。

## 依赖关系与数据流

本模块依赖 Agent 的 `ConversationGraph`、API 的 `ServerEvent` 和 Core 的错误契约。
API 层注入异步发送回调；用户输入进入 Graph，
Graph 消息块转换为协议事件后经回调返回客户端。

## 扩展方式与注意事项

未来工具进度或动作事件应在 Runtime 增加显式映射，不把传输对象带入 Graph。
每个连接必须创建独立 Session；MVP 只提供进程内并发控制。
取消、完成和错误只能有一个终态；发送失败后不得尝试再次向同一连接发送。
任何对外错误不得包含用户完整消息、供应商响应、内部异常文本或堆栈。
