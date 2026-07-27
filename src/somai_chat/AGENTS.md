# SOMAI Chat 组合根

## 模块简介与职责

`somai_chat` 是模块化单体的 Python 包。`main.py` 是唯一组合根：集中读取 `Settings`、配置 JSON 日志、创建模型和
能力服务及共享 HTTP 客户端、编译动态工具 LangGraph，并把 Provider 的中立错误分类 callback 注入 `ConversationRuntime`，最后装配健康路由、版本化
WebSocket 与包内静态调试台。

## 目录与公开入口

- `main.py`：`create_app(settings=None, runtime=None)` 支持生产装配和测试注入；`run()` 使用同一 Settings 启动 Uvicorn；模块级 `app` 供 ASGI 使用。
- `core/`：配置、错误、日志。
- `providers/`：OpenAI 兼容模型工厂。
- `agent/`：SOMAI Prompt、状态和带 Checkpointer 的 Graph facade。
- `weather/`：Open-Meteo 天气客户端与 LangChain 工具适配层。
- `time/`：固定为中国标准时间的 LangChain 查询工具。
- `application/`：一轮流式翻译和单连接生成生命周期。
- `api/`：HTTP/WebSocket 协议和连接边界。
- `web/`：随 wheel 分发、无需构建的调试台；可以作为管理后台的内嵌 Chat 工作区运行。
- `admin_web/`：由 `frontend/admin` 构建后随 wheel 分发的 Vue 3 + Element Plus 管理后台静态资源。
- `capabilities/`：天气、时间和搜索的固定配置、密钥处理与不可变工具快照。

## 装配与数据流

lifespan 成功时将 Settings、Runtime、能力服务和 ready 状态注入 `app.state`；依赖创建失败时应用仍能提供静态页和 liveness，但 readiness 为 503。组合根使用 Core 的拆分数据库字段生成连接 URL，Alembic 复用同一入口。生产与开发使用 MySQL 能力仓库，`test` 环境使用进程内仓库支持无需 MySQL 的真实传输测试。环境变量只补齐缺失能力记录。

客户端文本依次经过 `api -> application -> agent -> providers`，模型消息块再反向转换为统一服务端信封。
Application 不导入 Provider/OpenAI/httpx；组合根只注入 `Callable[[BaseException], bool]` 分类边界。
静态路径始终从包位置解析，不依赖当前工作目录。安全中间件为所有响应设置 CSP 和 `nosniff`；嵌入模式的
Chat 页面仅允许同源管理后台以 iframe 加载。

## 部署与注意事项

`python -m somai_chat.main` 是规范入口，host、port、development reload 与 Uvicorn WebSocket 传输硬上限均来自
Settings；应用可恢复帧上限独立用于解析前校验。Graph Checkpointer 和会话并发状态只在单进程内存中，重启丢失且
不支持多 worker/多实例。新增模块必须从组合根注入依赖，不得在业务模块读取环境变量或创建隐藏全局客户端。
本地依赖必须通过 `uv sync --locked --extra dev` 消费锁文件；容器 builder 使用固定 uv 版本创建非 editable
生产 venv，runtime 只复制该 venv。容器 healthcheck 从 `SOMAI_PORT` 读取探针端口，默认 8000。
