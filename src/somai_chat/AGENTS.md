# SOMAI Chat 组合根

## 模块简介与职责

`somai_chat` 是模块化单体的 Python 包。`main.py` 是唯一组合根：集中读取 `Settings`、配置 JSON 日志、创建模型、编译 LangGraph、创建 `ConversationRuntime`，并装配健康路由、版本化 WebSocket 与包内静态调试台。

## 目录与公开入口

- `main.py`：`create_app(settings=None, runtime=None)` 支持生产装配和测试注入；`run()` 使用同一 Settings 启动 Uvicorn；模块级 `app` 供 ASGI 使用。
- `core/`：配置、错误、日志。
- `providers/`：OpenAI 兼容模型工厂。
- `agent/`：SOMAI Prompt、状态和带 Checkpointer 的 Graph facade。
- `application/`：一轮流式翻译和单连接生成生命周期。
- `api/`：HTTP/WebSocket 协议和连接边界。
- `web/`：随 wheel 分发、无需构建的调试台。

## 装配与数据流

lifespan 成功时将 Settings、Runtime 和 ready 状态注入 `app.state`；依赖创建失败时应用仍能提供静态页和 liveness，但 readiness 为 503，WebSocket 以未就绪策略关闭。应用拥有的模型资源在 shutdown 安全关闭，测试注入的 Runtime 不由组合根关闭。

客户端文本依次经过 `api -> application -> agent -> providers`，模型消息块再反向转换为统一服务端信封。静态路径始终从包位置解析，不依赖当前工作目录。安全中间件为所有响应设置 CSP 和 `nosniff`，并让未指纹页面/资源不缓存。

## 部署与注意事项

`python -m somai_chat.main` 是规范入口，host、port、development reload 与 WebSocket 最大帧均来自 Settings。Graph Checkpointer 和会话并发状态只在单进程内存中，重启丢失且不支持多 worker/多实例。新增模块必须从组合根注入依赖，不得在业务模块读取环境变量或创建隐藏全局客户端。
