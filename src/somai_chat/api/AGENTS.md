# API 模块

## 模块简介

`api` 定义客户端与服务端事件协议，并提供健康检查与版本化 WebSocket 传输层。

管理员 API 位于 `/api/v1/admin`，通过管理员会话和 CSRF 保护客户端生命周期操作；客户端列表同时返回实时
WebSocket 在线状态和 Key 脱敏值。机器人 WebSocket 需要 Bearer Key，管理员 Chat 则通过已登录 Cookie 认证。

## 主要职责

- 严格校验客户端事件结构、类型、标识符和消息内容。
- 将所有非法客户端输入映射为稳定、安全的公开错误。
- 为服务端事件生成统一信封、唯一事件标识和 UTC 时间戳。
- 暴露不触发模型调用的 liveness/readiness 健康检查。
- 校验会话标识与 Origin，并把一个 WebSocket 连接绑定到一个 `ConversationSession`。
- 在独立生成任务运行期间持续接收消息、取消和 ping，并安全映射可恢复错误。

## 目录说明

- `capabilities.py`：能力列表、单卡原子保存和 CSRF 保护的 API Key 查看接口；列表不返回明文。

- `protocol.py`：客户端事件模型、解析入口和服务端事件通用信封。
- `health.py`：定义 `/health/live` 与 `/health/ready`。
- `images.py`：提供 `/api/v1/images` 图片上传与按 `image_id` 读取接口，校验图片格式并生成短期流程使用的资源标识；默认保存到当前目录的
  `media/uploads/<年>/<月>/<日>/`。
- `admin.py`：定义管理员会话与客户端管理 API，客户端列表合并进程内连接注册表的在线状态。
- `websocket.py`：定义 `/api/v1/chat/ws/{conversation_id}` 连接与接收循环，并在 Key 认证连接的生命周期内更新在线状态。
- `__init__.py`：包标识，不隐式导出协议实现。

## 核心模型

- `MessageCreate`：携带客户端消息标识与文本内容。
- `ActionResult`：携带端侧 `camera.capture` 的成功、拒绝、失败或取消结果；失败结果由 WebSocket 直接映射为用户可见的安全回复。
- `ResponseCancel`：携带待取消的响应标识。
- `Ping`：可携带关联标识的存活探测事件。
- `ServerEvent`：包含 `type`、`event_id`、`timestamp` 和 `data` 的服务端通用信封。

图片上传接口 `POST /api/v1/images` 接收 multipart 图片，返回 `image_id`、同源 `image_url`、媒体类型和字节数；
读取接口使用 `GET /api/v1/images/{image_id}`。对话消息可使用 `image_ids` 引用已上传图片，WebSocket 层将其解析为
服务端视觉分析器可读取的本机回环地址；`image_ids` 与旧的 `image_urls` 不能同时出现。服务端生成的图片 ID 不使用端侧
WebSocket Host 拼接 URL，避免局域网私有地址被视觉抓取器误判为 SSRF。
摄像头工具调用会产生 `action.request` 服务端事件，事件数据包含 `action=camera.capture`、`request_id`、摄像头方向、
拍摄数量和原因；端侧完成拍摄上传后，以带 `image_ids` 的新 `message.create` 继续对话。

## 核心接口

- `parse_client_event(payload, max_message_length)`：按 `type` 判别并解析客户端事件，
  应用动态消息长度限制。
- `ServerEvent.create(event_type, data)`：复制只读映射数据，
  创建带 `evt_` 前缀唯一标识和 UTC 时间戳的服务端事件。
- `router`（health）：暴露始终存活与基于应用状态的就绪探针。
- `router`（websocket）：从应用状态取得已构建配置和 Runtime，管理连接生命周期。

## 主要流程

原始载荷进入 `parse_client_event` 后，由 Pydantic 判别联合模型严格校验。
消息文本先去除首尾空白，再检查非空和动态长度上限。
任何结构、类型或内容错误都转换为
`SomaiError(INVALID_MESSAGE, "Invalid client event")`，不暴露 Pydantic 校验细节。

服务端业务数据通过 `ServerEvent.create` 包装为通用信封。
序列化为 JSON 时，UTC 时间戳使用 RFC 3339 的 `Z` 后缀。

WebSocket 先完成握手，再校验 `conversation_id`、运行时就绪状态和可选 Origin，
从而让真实客户端收到稳定的 1008 或 1013 WebSocket 关闭码，而不是 HTTP 403。
设备客户端未发送 Origin 时允许连接；浏览器 Origin 必须精确匹配 `Settings.allowed_origins`。
Origin 先按 Core 的标准规则规范化，畸形值按策略关闭。
校验通过后先发送 `conversation.ready`，其中包含会话 ID、非敏感模型名称、消息 code point 上限和
WebSocket 应用可恢复字节上限（不下发传输紧急硬上限）；随后创建的单连接 Session 在后台生成，
接收循环继续处理取消和 ping。
每个连接用异步锁串行化所有 `send_json`，避免后台生成与接收循环交错写入同一帧。
接收循环显式区分断开、文本和二进制帧；二进制、超出原始 UTF-8 字节限制、
非法、任意层对象 key 重复或递归过深的 JSON、未知事件、忙碌和取消目标不存在
都发送一个安全 `error` 信封且保持连接。
断开或传输失败后在 `finally` 等待 Session 关闭，取消生成并禁止后续发送。通过 Key 认证的设备连接在发送
`conversation.ready` 前注册到在线状态，并在断开时删除；同一客户端的新 Key 认证连接会以 `4001` 顶掉旧连接，
管理员 Cookie 会话不计入机器人在线状态。

管理员查看完整 Key 使用 CSRF 保护的 `POST /api/v1/admin/clients/{client_id}/key/reveal`；它只解密新建或轮换后
保存的密文，无法恢复迁移前的旧 Key。

Key 轮换请求只接受可选到期时间，不重复要求客户端创建时才需要的名称与描述字段。
创建重复名称的客户端返回 `409 Client name already exists`，不暴露数据库约束错误。

## 依赖关系

协议模型依赖 Pydantic 与 Core 错误契约。传输路由依赖 FastAPI、集中式配置、
Application 的 `ConversationRuntime`/`ConversationSession` 及 Core 日志约束；
不直接依赖 Agent 或模型供应商。

## 数据流

客户端 JSON 载荷经过严格协议模型后成为类型明确的事件，供后续应用层处理。
应用层产生的 JSON 兼容数据通过服务端通用信封发送给客户端。
应用组合根在 lifespan 中把配置与 Runtime 写入 `app.state`；
健康与 WebSocket 路由只读取注入结果，
readiness 不调用 Runtime 或模型。
每个连接生成独立 `connection_id`。连接生命周期日志始终同时携带 connection/conversation ID；
可恢复请求错误在映射点记录一次，Session 生成错误在发送回调记录一次，避免重复日志。

## 扩展方式

新增客户端事件时，应定义独立的严格 `data` 模型和字面量 `type`，加入判别联合，
并先覆盖合法与非法载荷测试。新增服务端事件优先复用通用信封；
仅在重复组装逻辑明显时增加小型工厂。
新增传输认证或来源策略时应保持握手后策略关闭，
并继续允许无 Origin 的受控设备客户端。

## 注意事项

- 协议模型拒绝未知字段，防止客户端和服务端协议静默漂移。
- 协议模型拒绝 `NaN` 与正负无穷，确保服务端信封始终可表示为严格 JSON。
- 所有协议字符串及 JSON 对象 key 必须是可编码为 UTF-8 的 Unicode scalar，禁止孤立 surrogate。
- 标识符只允许 ASCII 字母、数字、下划线和连字符，长度为 1 到 128。
- 对外错误必须使用 `core.errors.ErrorCode` 中的稳定错误码和安全消息，不得携带内部异常。
- 未就绪连接在握手后以 1013 关闭，策略错误以 1008 关闭，均不发送 `conversation.ready`。
- 传输日志只记录关联 ID、错误码和固定消息，不记录消息正文、模型文本或密钥。
- 公开错误码的最终集合为 `INVALID_MESSAGE`、`GENERATION_IN_PROGRESS`、`CANCEL_NOT_FOUND`、
  `MODEL_UNAVAILABLE`、`GENERATION_FAILED`；运行时未装配在握手阶段以 1013 关闭，不伪造成模型调用错误。
