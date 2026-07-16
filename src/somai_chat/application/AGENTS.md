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

`ConversationRuntime.stream(...)` 把会话标识映射为
LangGraph `thread_id`，过滤空的 AI 文本块，拼接最终文本并累加各流式块提供的 usage。
供应商 `openai.APIError` 及 httpx 传输/超时异常映射为 `MODEL_UNAVAILABLE` 和固定安全消息；取消原样传播，
普通编程、Graph 或未知异常映射为 `GENERATION_FAILED`，不得暴露原始错误。
Runtime 和 Session 都显式关闭下层异步流，
确保取消、关闭或发送失败返回时 Graph 锁已经释放。
流清理遵循主异常优先：已有取消或发送失败时抑制 cleanup 异常；
没有主异常时，cleanup 错误进入统一安全错误映射。

`ConversationSession.start()` 同步返回本轮 `response_id` 并在后台泵送事件；
活跃时再次调用会返回稳定忙碌错误。
`cancel()` 只取消匹配的活跃响应，等待任务停止后发送一次 cancelled；
`close()` 停止任务且不发送终态。
若 completed 或 error 已取得终态发送权，`cancel()` 等待该发送结束并返回 `CANCEL_NOT_FOUND`，
不得中断已经开始的终态发送。
cancelled 确认发送由当前 generation 的取消任务持有；
发送完成或失败前 Session 保持忙碌。
`close()` 会取消并等待该任务，返回后不会再发送 cancelled；
关闭后的 Session 拒绝新一轮生成。
并发 close 只会首次取消 pump；后续调用通过 shield 等待同一 cleanup，
取消某个等待者不会把取消继续传播到 pump 或其他 close。
close 已开始后到达的 cancel 返回 `CANCEL_NOT_FOUND`，不得取得 owner 或再次取消 pump。
异步发送回调不得调用当前 Session 的 `cancel()` 或 `close()`；
这种生命周期重入会在修改状态前抛出固定的内部 `RuntimeError`，避免任务自取消或自等待。

## 依赖关系与数据流

本模块依赖 Agent 的 `ConversationGraph`、API 的 `ServerEvent` 和 Core 的错误契约。
API 层注入异步发送回调；用户输入进入 Graph，
Graph 消息块转换为协议事件后经回调返回客户端。

## 扩展方式与注意事项

未来工具进度或动作事件应在 Runtime 增加显式映射，不把传输对象带入 Graph。
每个连接必须创建独立 Session；MVP 只提供进程内并发控制。
取消、完成和错误只能有一个终态；发送失败后不得尝试再次向同一连接发送。
任何对外错误不得包含用户完整消息、供应商响应、内部异常文本或堆栈。
取消时 Graph 可能已经 checkpoint 本轮用户消息，但只有完整 AI 消息才构成已完成回复；客户端不得把
`response.delta` 的 partial 文本当作持久化承诺。此语义由 Graph 流关闭与取消测试共同约束。
