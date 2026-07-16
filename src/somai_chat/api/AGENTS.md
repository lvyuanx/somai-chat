# API 模块

## 模块简介

`api` 定义与传输方式无关的客户端和服务端事件协议。
当前模块只负责协议模型与解析，不包含 WebSocket 路由。

## 主要职责

- 严格校验客户端事件结构、类型、标识符和消息内容。
- 将所有非法客户端输入映射为稳定、安全的公开错误。
- 为服务端事件生成统一信封、唯一事件标识和 UTC 时间戳。

## 目录说明

- `protocol.py`：客户端事件模型、解析入口和服务端事件通用信封。
- `__init__.py`：包标识，不隐式导出协议实现。

## 核心模型

- `MessageCreate`：携带客户端消息标识与文本内容。
- `ResponseCancel`：携带待取消的响应标识。
- `Ping`：可携带关联标识的存活探测事件。
- `ServerEvent`：包含 `type`、`event_id`、`timestamp` 和 `data` 的服务端通用信封。

## 核心接口

- `parse_client_event(payload, max_message_length)`：按 `type` 判别并解析客户端事件，
  应用动态消息长度限制。
- `ServerEvent.create(event_type, data)`：创建带 `evt_` 前缀唯一标识和 UTC 时间戳的服务端事件。

## 主要流程

原始载荷进入 `parse_client_event` 后，由 Pydantic 判别联合模型严格校验。
消息文本先去除首尾空白，再检查非空和动态长度上限。
任何结构、类型或内容错误都转换为
`SomaiError(INVALID_MESSAGE, "Invalid client event")`，不暴露 Pydantic 校验细节。

服务端业务数据通过 `ServerEvent.create` 包装为通用信封。
序列化为 JSON 时，UTC 时间戳使用 RFC 3339 的 `Z` 后缀。

## 依赖关系

本模块依赖 Pydantic，以及 `core.errors` 提供的稳定错误码与安全异常。
模块不依赖传输层、Agent 或模型供应商。

## 数据流

客户端 JSON 载荷经过严格协议模型后成为类型明确的事件，供后续应用层处理。
应用层产生的 JSON 兼容数据通过服务端通用信封发送给客户端。

## 扩展方式

新增客户端事件时，应定义独立的严格 `data` 模型和字面量 `type`，加入判别联合，
并先覆盖合法与非法载荷测试。新增服务端事件优先复用通用信封；
仅在重复组装逻辑明显时增加小型工厂。

## 注意事项

- 协议模型拒绝未知字段，防止客户端和服务端协议静默漂移。
- 标识符只允许 ASCII 字母、数字、下划线和连字符，长度为 1 到 128。
- 对外错误必须使用 `core.errors.ErrorCode` 中的稳定错误码和安全消息，不得携带内部异常。
- 本模块不得提前实现 WebSocket 连接、并发控制或生成流程。
