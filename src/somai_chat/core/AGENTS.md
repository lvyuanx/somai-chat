# Core 模块

## 模块简介

`core` 提供 SOMAI Chat 中不依赖业务流程的基础能力，
当前负责集中式配置管理、稳定错误契约与基于 Loguru 的统一日志。

## 主要职责

- 从环境变量和本地 `.env` 文件加载配置。
- 在应用启动前校验运行环境、模型连接参数和输入限制。
- 以敏感类型保存 API Key，避免其出现在对象文本表示中。
- 定义跨模块使用的稳定错误码和只包含安全公开信息的异常。
- 只为 `somai_chat` namespace 输出 JSON 日志，并隔离可能含供应商动态内容的第三方 namespace。

## 目录说明

- `config.py`：定义 `Settings` 配置模型和缓存的配置入口。
- `errors.py`：定义稳定错误码 `ErrorCode` 和安全异常 `SomaiError`。
- `logging.py`：定义 Loguru sink、标准库拦截器、控制台配色与 `JsonFormatter` 兼容入口。
- `__init__.py`：包标识，不隐式导出实现。

## 核心类

- `Settings`：应用唯一配置模型，提供严格字段约束和安全默认值。
- `ErrorCode`：跨模块共享且可序列化的稳定公开错误码。
- `SomaiError`：只保存错误码与安全消息的应用异常。

## 核心接口

- `get_settings()`：返回进程内缓存的 `Settings` 实例，供组合根注入其他模块。
- `SomaiError(code, safe_message)`：创建可安全转换为字符串的应用错误。
- `configure_logging(level, log_dir=None, stream=None)`：幂等配置按日期切分的全量、项目与错误日志，并保留 root/Uvicorn handler。
- `setup_logging(log_dir=None, log_level=None, stream=None)`：向后兼容的日志配置别名。
- `get_logger()`：返回绑定 `source="project"` 的 Loguru logger。
- `JsonFormatter`：输出时间、级别、logger、固定消息及允许的关联字段，供测试和兼容调用使用。

## 主要流程

应用组合根首次调用 `get_settings()`，Pydantic Settings 按 `SOMAI_` 前缀读取环境变量并完成校验；
后续调用复用同一实例。

## 依赖关系

本模块的配置能力依赖 Pydantic 与 Pydantic Settings；错误契约和日志能力只依赖 Python 标准库。
本模块不依赖 API、Application、Agent 或 Provider 模块。

## 数据流

环境变量或 `.env` 文件进入 `Settings`，经校验后由应用组合根注入使用方。
业务模块不直接读取环境变量。
模块内部错误由使用方映射为 `ErrorCode` 和安全消息后跨边界传递。
日志记录只接收 `connection_id`、`conversation_id`、`message_id`、`response_id`、
`error_code` 等关联字段，以及 `client_id`、`client_count`、`online_count`、`capability`、
`capability_count`、`enabled`、`event_type`、`reject_reason`、`image_count`、`environment`、
`model` 和能力启用状态等白名单安全字段；项目记录通过 `source="project"` 路由到项目日志与控制台，
输出时使用中文消息、中文字段名和部分中文值，不会自动序列化任意额外字段。

## 配置说明

必填项为 OpenAI 兼容 API Key 与模型名称，两者都会去除首尾空白并拒绝空值。
服务监听地址/端口、模型基础 URL、和风天气专属 API Host、天气服务超时、生成参数、消息字符数、WebSocket 原始文本字节数
及允许来源均在此集中定义。
MySQL 使用 `DATABASE_USER/PASSWORD/HOST/PORT/NAME` 拆分配置，并由 `URL.create()` 集中生成异步连接 URL；密码
使用敏感类型保存。管理员用户名默认为 `admin`、密码默认为 `123456`，会话密钥、客户端 Key
pepper 与加密密钥均使用敏感类型保存。`SOMAI_CAPABILITY_SECRET_ENCRYPTION_SECRET` 是专用于能力 API Key 的独立
加密密钥，不得与客户端 Key 或其他密钥材料复用。开发环境可使用示例占位值；生产环境拒绝默认管理员密码和任何包含
`replace`、`change-me`、`your-secret` 或 `placeholder` 的管理员密钥材料和数据库密码，包括能力加密密钥。
`max_websocket_message_bytes` 默认 32768，是应用解析前可恢复阈值；
`websocket_transport_max_bytes` 默认 1048576，是 Uvicorn 紧急硬上限，必须为正且不小于应用阈值。
`media_root` 默认是当前工作目录下的 `media`，`log_dir` 默认是当前工作目录下的 `logs`，
图片上传服务在其下按 `uploads/<年>/<月>/<日>/` 保存图片；
可通过 `SOMAI_MEDIA_ROOT` 配置为其他目录。
`python -m somai_chat.main` 先解析同一份 Settings，再把 host、port、开发环境 reload 状态及
`websocket_transport_max_bytes` 传给 Uvicorn。
允许来源只接受不含路径、查询、片段和用户信息的 HTTP/HTTPS Origin；主机转小写，
默认 80/443 端口省略后再保存，localhost、IPv4 和 IPv6 均可使用。

## 扩展方式

新增全局配置时，应先添加校验测试，再扩展 `Settings` 字段和 `.env.example`；
模块专属配置应保持清晰命名。新增公开错误时，应先确定稳定错误码及安全消息边界，
再扩展 `ErrorCode`。

## 注意事项

不得记录或序列化 API Key 明文。`get_settings()` 的缓存仅适合进程级不可变配置；
测试若修改环境变量，应显式清理缓存。
`SomaiError` 不得保存供应商响应、堆栈或其他内部异常。
日志调用方必须使用固定消息，不得把用户正文、模型文本、API Key
或供应商原始错误插入日志消息。
结构化关联字段包括 `connection_id`、`conversation_id`、`message_id`、
`response_id` 与 `error_code`；常用安全 extra 字段必须进入白名单后才会输出，并在项目日志中使用中文展示名。
root 与 Uvicorn 保留自身运维 handler 且不被替换；`langchain`、`langchain_openai`、`openai`、
`httpx`、`httpcore` namespace 只通过拦截器进入统一日志流，避免动态供应商诊断进入受信任 project 输出。
容器和 wheel 不携带 `.env`；运行时必须显式注入必填模型字段。模型配置不可用时组合根降级为
liveness/静态页可用、readiness 503，而不是在健康探针中请求供应商。
