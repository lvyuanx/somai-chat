# SOMAI Chat

SOMAI Chat 是 SOMAI 具身智能系统的文本对话中枢 MVP。端侧负责语音采集、ASR 与 TTS；本服务只接收已经转写的文本，使用 LangGraph 编排 OpenAI 兼容模型，并通过 WebSocket 流式返回文本。

## MVP 边界与架构

当前包含 FastAPI 服务、LangGraph 多轮会话、进程内 Checkpointer、流式 WebSocket、取消/心跳、健康检查和无构建步骤的浏览器调试台。不包含音频、ASR、TTS、认证、知识库、联网搜索、真实设备动作、持久化或分布式会话。

```text
端侧 / 浏览器调试台
        ⇅ WebSocket
api（协议、Origin、帧限制、连接）
        ↓
application（流式事件、并发、取消；只调用中立错误分类 callback）
        ↓
agent（SOMAI Prompt、LangGraph、内存 Checkpoint）
        ⇅
providers（OpenAI 兼容 Chat Model 与供应商异常分类）
```

`core` 提供配置、错误与安全日志；`main.py` 装配应用；`web` 保存随 wheel 分发的静态调试台。SOMAI 的稳定身份是自然、沉稳、友好的 AI 助手：默认跟随用户语言，输出适合 TTS 的短句；没有接入感知或动作工具时，不声称已经观察或执行。

## 本地运行

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。

```bash
cp .env.example .env
make install
make dev
```

打开 `http://localhost:8000/`。`make dev` 使用 `python -m somai_chat.main`，因此监听地址、端口、development reload
和 WebSocket 传输硬上限均来自 Settings。

## 配置

所有字段使用 `SOMAI_` 前缀，`.env.example` 只有占位值，禁止提交真实密钥。

后台管理使用 MySQL。先创建数据库并执行迁移：

```bash
mysql -u root -p -e 'CREATE DATABASE somai_chat CHARACTER SET utf8mb4'
SOMAI_DATABASE_URL='mysql+asyncmy://root:<password>@127.0.0.1:3306/somai_chat' \
  uv run alembic upgrade head
```

开发环境默认管理员为 `admin` / `123456`；生产环境必须覆盖管理员密码、
`SOMAI_ADMIN_SESSION_SECRET` 与 `SOMAI_CLIENT_KEY_PEPPER`。后台入口为 `/admin`。
创建机器人客户端时只显示一次完整 Key。机器人建立 WebSocket 时必须发送
`Authorization: Bearer somai_sk_<key-id>_<secret>`；管理员从 Chat 菜单进入时使用登录会话。

| 环境变量 | 默认/示例 | 说明 |
|---|---|---|
| `SOMAI_ENVIRONMENT` | `development` | `development`、`test` 或 `production`；development 启用 reload |
| `SOMAI_LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING` 或 `ERROR` |
| `SOMAI_HOST` | `0.0.0.0` | Uvicorn 监听地址 |
| `SOMAI_PORT` | `8000` | Uvicorn 监听端口 |
| `SOMAI_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 HTTP 基地址 |
| `SOMAI_OPENAI_API_KEY` | 必填 | API Key；使用 `SecretStr`，不得写入日志 |
| `SOMAI_OPENAI_MODEL` | 必填 | 兼容端点提供的模型名 |
| `SOMAI_DATABASE_URL` | 本地 MySQL 示例 | SQLAlchemy 异步 MySQL 连接 URL，使用 `mysql+asyncmy` 方言 |
| `SOMAI_ADMIN_USERNAME` | `admin` | 后台超级管理员用户名 |
| `SOMAI_ADMIN_PASSWORD` | `123456` | 后台超级管理员密码；生产环境必须覆盖默认值 |
| `SOMAI_ADMIN_SESSION_SECRET` | 必填 | 管理员会话签名密钥；生产环境不得使用占位值 |
| `SOMAI_CLIENT_KEY_PEPPER` | 必填 | 客户端 Key 摘要 pepper；生产环境不得使用占位值 |
| `SOMAI_MODEL_TEMPERATURE` | `0.4` | 生成温度，范围 0–2 |
| `SOMAI_MODEL_MAX_TOKENS` | `800` | 最大输出 token 数 |
| `SOMAI_MODEL_TIMEOUT_SECONDS` | `30` | 单次模型请求超时秒数 |
| `SOMAI_VISION_BASE_URL` | DashScope compatible mode | Qwen3-VL OpenAI 兼容 HTTP 基地址；与以下两个字段同时配置才启用视觉能力 |
| `SOMAI_VISION_API_KEY` | 可选 | DashScope API Key；使用 `SecretStr`，不得写入日志 |
| `SOMAI_VISION_MODEL` | `qwen3-vl-plus` | 仅携带图片时调用的视觉模型 |
| `SOMAI_VISION_TIMEOUT_SECONDS` | `30` | 单次视觉模型请求超时秒数 |
| `SOMAI_MAX_IMAGE_URLS` | `4` | 单条消息可携带的图片 URL 上限 |
| `SOMAI_MAX_IMAGE_DOWNLOAD_BYTES` | `8388608` | 服务端下载单张图片的字节上限 |
| `SOMAI_QWEATHER_API_HOST` | 必填 | 和风天气控制台提供的专属 API Host |
| `SOMAI_QWEATHER_API_KEY` | 必填 | 和风天气项目 API Key；使用 `SecretStr`，不得写入日志 |
| `SOMAI_WEATHER_TIMEOUT_SECONDS` | `5` | 单次和风天气请求超时秒数 |
| `SOMAI_MAX_MESSAGE_LENGTH` | `8000` | 用户消息 Unicode code point 上限 |
| `SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES` | `32768` | 应用解析前文本 UTF-8 字节上限；超限返回 `INVALID_MESSAGE`，连接继续 |
| `SOMAI_WEBSOCKET_TRANSPORT_MAX_BYTES` | `1048576` | Uvicorn 紧急帧硬上限；不得小于应用上限，超限以 1009 关闭 |
| `SOMAI_ALLOWED_ORIGINS` | localhost 两项 | JSON 数组；浏览器 Origin 必须精确匹配，非浏览器设备可不发送 Origin |

## HTTP 与 WebSocket

- `GET /`：调试台。
- `GET /assets/{name}`：包内静态资源。
- `GET /health/live`：进程存活，不调用模型。
- `GET /health/ready`：配置、Graph 和静态资源已装配；不探测供应商。
- `ws://localhost:8000/api/v1/chat/ws/{conversation_id}`：对话连接。生产 TLS 使用 `wss://`。

`conversation_id` 以及协议 ID 只允许 1–128 个 ASCII 字母、数字、`_`、`-`。所有服务端事件使用统一信封：

```json
{"type":"conversation.ready","event_id":"evt_...","timestamp":"2026-07-16T10:24:17.102Z","data":{"conversation_id":"conv_demo","model":"example-model","max_message_length":8000,"max_websocket_message_bytes":32768}}
```

客户端事件示例：

```json
{"type":"message.create","data":{"message_id":"msg_1","content":"你好，SOMAI"}}
{"type":"response.cancel","data":{"response_id":"resp_..."}}
{"type":"ping","data":{"correlation_id":"probe_1"}}
```

服务端一轮事件按 `response.started` → 零到多个 `response.delta` → `response.completed` 排列；取消成功以 `response.cancelled` 终止，心跳返回 `pong`。

```json
{"type":"response.started","event_id":"evt_...","timestamp":"2026-07-16T10:24:18Z","data":{"response_id":"resp_...","message_id":"msg_1"}}
{"type":"response.delta","event_id":"evt_...","timestamp":"2026-07-16T10:24:18Z","data":{"response_id":"resp_...","delta":"你好"}}
{"type":"response.completed","event_id":"evt_...","timestamp":"2026-07-16T10:24:19Z","data":{"response_id":"resp_...","content":"你好。","usage":null}}
{"type":"pong","event_id":"evt_...","timestamp":"2026-07-16T10:24:19Z","data":{"correlation_id":"probe_1"}}
```

终止事件到达前不要发送下一条消息。同一连接重复生成返回 `GENERATION_IN_PROGRESS` 且连接保持可用。错误信封的
`data` 包含稳定 `code` 和安全 `message`，可能附带关联 ID：`INVALID_MESSAGE`、
`GENERATION_IN_PROGRESS`、`CANCEL_NOT_FOUND`、`MODEL_UNAVAILABLE`、`GENERATION_FAILED`。
供应商 API 或网络/超时错误统一返回 `MODEL_UNAVAILABLE` 和固定安全消息；未知内部错误返回
`GENERATION_FAILED`，两者均不包含 URL、Key 或供应商原文。取消只接受当前 `response_id`；已完成或不匹配时返回
`CANCEL_NOT_FOUND`。客户端可随时发送 `ping`，无需等待生成结束。

## 开发与验证

```bash
make format
make lint
make typecheck
make test
make check
```

`make install` 运行 `uv sync --locked --extra dev`，按 `uv.lock` 建立 `.venv` 并以 editable 模式安装项目；
也可直接运行 `.venv/bin/python -m pytest -q`。浏览器状态机的 Node harness 为：

```bash
node tests/js/web_console_state.mjs
node tests/js/console_view.mjs
```

## Docker

```bash
docker build -t somai-chat:mvp .
docker run --rm --env-file .env -e SOMAI_ENVIRONMENT=production -p 8000:8000 somai-chat:mvp
```

`.env.example` 默认为 development，上述命令必须覆盖为 production，避免容器启动 reload；正式环境文件应直接设置
`SOMAI_ENVIRONMENT=production`。镜像使用 Python 3.12 slim，builder 固定 uv 0.11.13 并执行锁定同步；runtime
只复制可运行 venv，不包含 uv 或编译工具，并以非 root `somai` 用户执行 `python -m somai_chat.main`。
容器需要 `SOMAI_HOST=0.0.0.0`，healthcheck 会读取运行时 `SOMAI_PORT`。

自定义容器端口时，环境变量与 `-p` 的容器端端口必须一致，例如：

```bash
docker run --rm --env-file .env -e SOMAI_ENVIRONMENT=production -e SOMAI_PORT=9000 -p 9000:9000 somai-chat:mvp
```

## 部署、安全与扩展

MVP 的 Checkpointer、会话锁和生成状态都在单进程内存中：重启即丢失，不能直接增加 Uvicorn worker、容器副本或多实例。扩容前必须替换为持久化/共享 Checkpointer 与分布式会话锁。

应用日志仅由 `somai_chat` namespace 输出 JSON，并记录固定消息、关联 ID 和稳定错误码；root/Uvicorn 运维日志不经
应用 JSON formatter，LangChain/OpenAI/httpx/httpcore 动态日志被隔离。任何日志都不得记录 API Key、完整用户消息、
完整模型回复或供应商原始错误。文本同时受 code point、应用可恢复 UTF-8 字节上限与更大的传输硬上限约束。

未来扩展点：向 `build_conversation_graph` 注入持久 Checkpointer；在 Agent Graph 增加明确的工具/动作节点和运行时能力清单；端侧通过当前文本 WebSocket 前后接入 ASR/TTS。新增事件应保持统一信封和既有终态语义。

## 故障排查

- `/health/live` 可用但 `/health/ready` 为 503：检查必填模型配置与启动日志；ready 不会替你验证外部模型。
- WebSocket 立即以 1008 关闭：检查会话 ID、浏览器 Origin 和 `SOMAI_ALLOWED_ORIGINS`。
- 收到 `INVALID_MESSAGE`：检查严格 JSON（包括任意层重复 key）、事件类型、未知字段、ID、字符数和应用帧上限。
- 收到 `MODEL_UNAVAILABLE`：检查兼容端点、模型名、Key、网络和超时；对外事件不会包含供应商原文。
- 收到 `GENERATION_FAILED`：服务端遇到未分类内部生成错误；检查受信任应用日志。
- 浏览器无法连接：确认页面与服务端 host/port、HTTP/HTTPS 对应的 `ws`/`wss` 以及反向代理 Upgrade 配置。
- 重启后对话消失或多 worker 上下文不一致：这是进程内 MVP 的已知边界，不是持久会话实现。
