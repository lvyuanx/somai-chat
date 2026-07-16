# SOMAI Chat MVP 设计

## 1. 目标

构建一个以 LangChain 与 LangGraph 为核心的企业级具身智能对话后端 MVP。系统接收端侧已经转写的文本，
通过 OpenAI 兼容模型生成回复，并经 WebSocket 流式返回文本事件。

本项目不负责语音采集、ASR、TTS 或真实设备动作。端侧语音项目和浏览器调试页共享同一套 WebSocket 协议。

## 2. MVP 范围

### 2.1 包含

- 基于 FastAPI 的单体服务。
- 基于 LangGraph 的对话核心图。
- 通过环境变量配置的 OpenAI 兼容模型。
- 按 `conversation_id` 隔离的进程内会话记忆。
- 支持多轮消息、流式回复、取消生成和心跳的 WebSocket API。
- 健康检查、结构化日志、统一异常和稳定错误码。
- 无前端构建步骤的原生 HTML、CSS、JavaScript 调试页面。
- 单元测试与 WebSocket 集成测试。
- Docker、Makefile、环境变量示例和项目文档。

### 2.2 不包含

- 音频上传、音频流、ASR 和 TTS。
- PostgreSQL、Redis 或其他持久化存储。
- 用户长期记忆、画像提取和跨会话记忆。
- 知识库、联网搜索或真实设备工具。
- 用户认证、租户管理和管理后台。
- 微服务、消息队列和分布式任务。

## 3. 总体架构

采用模块化单体：一个 FastAPI 进程同时提供健康检查、WebSocket API 和静态调试页。内部模块边界如下：

```text
端侧 / 调试页
      ⇅ WebSocket
API 协议与连接层
      ↓
Application 对话用例
      ↓
LangGraph 对话核心图
      ⇅
OpenAI 兼容模型
```

LangGraph 使用内存 Checkpointer 保存会话状态。`conversation_id` 同时作为 LangGraph `thread_id`，因此同一进程内的
多轮对话能够延续，服务重启后状态清空。

模型与 Checkpointer 都通过工厂或接口装配。未来切换数据库 Checkpointer、增加工具节点或替换模型服务时，不改变
WebSocket 协议和对话用例的公开接口。

## 4. 模块结构

```text
somai-chat/
├── src/somai_chat/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   └── logging.py
│   ├── api/
│   │   ├── health.py
│   │   ├── protocol.py
│   │   └── websocket.py
│   ├── application/
│   │   └── conversation.py
│   ├── agent/
│   │   ├── graph.py
│   │   ├── prompts.py
│   │   └── state.py
│   ├── providers/
│   │   └── llm.py
│   └── web/
│       ├── index.html
│       ├── app.css
│       └── app.js
├── tests/
│   ├── unit/
│   └── integration/
├── docs/
├── pyproject.toml
├── .env.example
├── Dockerfile
├── Makefile
└── README.md
```

各功能模块维护自己的 `AGENTS.md`。根目录使用 `PROJECT_AGENTS.md` 记录本项目技术栈、接口约定、测试与部署约束。

### 4.1 `core`

负责应用配置、日志初始化、领域无关异常与公共基础能力。配置只从环境变量读取，业务模块不直接访问环境变量。

### 4.2 `api`

负责 HTTP 健康检查、WebSocket 生命周期、输入事件校验和输出事件序列化。该层不直接调用模型。

### 4.3 `application`

负责一次对话生成用例、连接级并发控制、取消任务和应用异常映射。它协调 Agent，但不包含 Prompt 或模型供应商细节。

### 4.4 `agent`

负责 LangGraph State、系统提示词和 Graph 构建。MVP 的核心流为：输入校验后的用户消息进入会话状态，模型根据系统身份
与历史消息流式生成回复，最终 AI 消息写回会话状态。

### 4.5 `providers`

负责根据配置创建 `ChatOpenAI` 兼容客户端。业务层只依赖 LangChain Chat Model 接口。

### 4.6 `web`

负责无构建步骤的调试运行台。页面只使用公开 WebSocket 协议，不依赖后端内部模块。

## 5. SOMAI 身份

SOMAI 是通用具身智能助手，也是端侧设备的对话与认知中枢。MVP 只具备语言交流能力。

稳定身份原则：

- 自然、沉稳、友好、简洁，不使用夸张讨好的表达。
- 默认使用用户所用语言回复。
- 优先使用短句和口语化结构，使输出适合后续 TTS 播放。
- 只根据对话上下文和已接入能力回答。
- 没有视觉、位置、设备状态或动作工具时，不声称已经观察或执行。
- 收到无法执行的动作请求时，明确说明当前能力边界，并提供语言层面的帮助。
- 信息不足时承认不确定，必要时只提出一个关键澄清问题。
- 拒绝危险或越权操作，并在可行时提供安全替代建议。
- 被问及身份时，说明自己是运行于 SOMAI 系统中的 AI 助手，不冒充真人。

Prompt 分为稳定身份与运行时上下文两部分。未来新增设备能力时，只向运行时上下文注入可用能力清单，避免核心人格随工具
实现发生漂移。

## 6. LangGraph 设计

MVP 使用一条最小对话主链，不加入虚假的意图路由或工具节点。

状态至少包含 LangGraph 消息列表。会话 ID 不写入消息内容，而是通过 Graph 配置的 `thread_id` 传入。Graph 由应用启动阶段
构建一次，并使用共享的内存 Checkpointer 编译。

对每条有效用户消息：

1. API 层完成协议与文本长度校验。
2. Application 层确认会话当前没有正在运行的生成任务。
3. 用户消息作为新输入进入 Graph。
4. 模型节点组合系统身份、运行时能力说明和会话消息。
5. LangGraph/LangChain 流式事件被转换为 `response.delta`。
6. 生成结束后发送 `response.completed`，Graph Checkpointer 保存最终 AI 消息。

取消生成时，Application 层取消当前异步任务并发送 `response.cancelled`。已产生但未完成的文本不作为一条完整 AI 消息承诺给
客户端。具体 Checkpointer 行为由测试约束，确保取消后下一轮不会包含不完整回复。

## 7. WebSocket 协议

连接地址：

```text
/api/v1/chat/ws/{conversation_id}
```

`conversation_id` 由客户端生成，必须满足长度和字符集限制。一个连接可以持续发送多轮消息；同一个会话在一个连接内同一时间
只允许一个生成任务。

所有事件使用统一信封：

```json
{
  "type": "response.delta",
  "event_id": "evt_01...",
  "timestamp": "2026-07-16T10:24:17.102Z",
  "data": {}
}
```

### 7.1 客户端事件

- `message.create`：包含唯一 `message_id` 和非空 `content`。
- `response.cancel`：包含当前 `response_id`。
- `ping`：可包含客户端自定义的关联值。

### 7.2 服务端事件

- `conversation.ready`：连接建立完成，返回 `conversation_id`。
- `response.started`：返回本轮唯一 `response_id` 和对应 `message_id`。
- `response.delta`：返回 `response_id` 和增量文本 `delta`。
- `response.completed`：返回 `response_id`、完整文本和模型可提供的 usage 数据。
- `response.cancelled`：确认本轮生成已停止。
- `pong`：回应客户端心跳。
- `error`：包含稳定 `code`、安全的 `message` 和可选关联 ID。

客户端在收到 `response.completed`、`response.cancelled` 或本轮终止性的 `error` 后，才可发送下一条消息。违反规则时服务端返回
`GENERATION_IN_PROGRESS`，但不关闭健康连接。

未来工具与动作事件通过新增 `type` 扩展，不改变通用信封或已有事件字段。

## 8. 错误处理

稳定错误码至少包括：

- `INVALID_MESSAGE`：事件结构、ID 或文本不合法。
- `GENERATION_IN_PROGRESS`：当前会话已有生成任务。
- `CANCEL_NOT_FOUND`：取消目标与当前任务不匹配。
- `MODEL_UNAVAILABLE`：模型配置缺失或供应商不可用。
- `GENERATION_FAILED`：生成过程中发生未分类错误。

协议校验错误和可恢复的应用错误通过 `error` 事件返回。不可恢复的连接错误在发送安全错误后关闭连接。错误事件不包含堆栈、
API Key、供应商原始响应或其他敏感信息；完整异常通过服务端结构化日志记录。

日志包含 `conversation_id`、`message_id`、`response_id` 和错误码。默认不记录完整用户消息与模型回复。

## 9. 健康检查

- `GET /health/live`：进程可响应时返回成功。
- `GET /health/ready`：配置可解析、Graph 已构建且静态资源可用时返回成功。

就绪检查不请求模型供应商，避免健康探针产生费用或受外部模型短暂抖动影响。真实模型错误由 WebSocket 错误事件与运行指标反映。

## 10. 调试运行台

页面采用工业设备控制台风格，使用暖灰、黑色与信号橙。

- 中间区域展示用户与 SOMAI 消息、Markdown 内容和流式光标。
- 左侧展示 WebSocket 状态、当前模型和 `conversation_id`。
- 右侧展示实时事件轨迹。
- 支持 Enter 发送、Shift+Enter 换行、新建会话和清空本地显示。
- 生成过程中发送按钮切换为停止按钮，并发送 `response.cancel`。
- 页面刷新时从浏览器本地存储恢复 `conversation_id`；后端进程重启后服务端历史仍会清空。
- 连接意外断开时展示重连状态并有限次数重试，不自动重发可能已经被处理的消息。
- 小屏幕隐藏左右调试栏，保留聊天与输入区域。

页面由 FastAPI 作为静态资源提供，无 Node.js、打包器或前端框架依赖。

## 11. 配置

环境变量包含：

- 应用环境、日志级别和服务监听配置。
- OpenAI 兼容 `base_url`、`api_key`、`model`。
- 模型 temperature、最大输出 token 和请求超时。
- 用户消息最大长度。
- 允许的 WebSocket Origin 列表。

`.env.example` 只提供示例值，不提交真实密钥。配置模型使用严格校验，并在应用启动或就绪检查阶段报告缺失项。

## 12. 测试策略

单元测试使用可流式输出的 Fake Chat Model，不访问网络：

- 配置默认值、环境变量解析和敏感字段隐藏。
- 客户端事件校验和服务端事件序列化。
- SOMAI Prompt 包含身份、能力边界和语言风格约束。
- 不同 `conversation_id` 的状态隔离和同会话多轮记忆。
- 正常生成、模型失败、重复生成、无效取消和成功取消。

集成测试使用 FastAPI TestClient 建立 WebSocket：

- 连接后收到 `conversation.ready`。
- `message.create` 产生 started、一个或多个 delta、completed 的有序事件流。
- 非法事件返回稳定错误且连接保持可用。
- 忙碌会话拒绝第二条消息。
- ping 获得 pong。
- 调试页和健康检查可访问。

质量门禁为 Ruff 格式与静态检查、mypy 类型检查、pytest 测试。Docker 镜像构建作为交付验证的一部分。

## 13. 安全与部署

- Docker 容器使用非 root 用户。
- WebSocket 校验 Origin，并限制单条消息大小。
- 不在日志、事件或前端中暴露 API Key。
- 不将供应商异常原文直接返回客户端。
- 单进程部署是 MVP 的明确约束，因为内存 Checkpointer 和连接级并发控制不跨进程共享。

若未来扩展为多实例，必须先将 Checkpointer 与会话锁替换为共享基础设施，再增加实例数；不能直接横向扩容当前内存实现。

## 14. 验收标准

- 按 README 的本地步骤可以启动服务并打开调试页面。
- 使用 OpenAI 兼容配置时，页面能通过 WebSocket 展示流式模型回复。
- 同一 `conversation_id` 在进程存活期间保持多轮上下文，不同 ID 互不影响。
- 用户可以取消正在生成的回复，并继续下一轮消息。
- 错误以稳定协议事件返回，服务端日志包含关联 ID 且不泄露敏感信息。
- 健康检查、静态检查、类型检查、单元测试和集成测试全部通过。
- Docker 镜像可构建，并以非 root 用户运行服务。
