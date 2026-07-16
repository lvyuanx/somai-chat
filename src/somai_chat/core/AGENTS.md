# Core 模块

## 模块简介

`core` 提供 SOMAI Chat 中不依赖业务流程的基础能力，
当前负责集中式配置管理与稳定错误契约。

## 主要职责

- 从环境变量和本地 `.env` 文件加载配置。
- 在应用启动前校验运行环境、模型连接参数和输入限制。
- 以敏感类型保存 API Key，避免其出现在对象文本表示中。
- 定义跨模块使用的稳定错误码和只包含安全公开信息的异常。

## 目录说明

- `config.py`：定义 `Settings` 配置模型和缓存的配置入口。
- `errors.py`：定义稳定错误码 `ErrorCode` 和安全异常 `SomaiError`。
- `__init__.py`：包标识，不隐式导出实现。

## 核心类

- `Settings`：应用唯一配置模型，提供严格字段约束和安全默认值。
- `ErrorCode`：跨模块共享且可序列化的稳定公开错误码。
- `SomaiError`：只保存错误码与安全消息的应用异常。

## 核心接口

- `get_settings()`：返回进程内缓存的 `Settings` 实例，供组合根注入其他模块。
- `SomaiError(code, safe_message)`：创建可安全转换为字符串的应用错误。

## 主要流程

应用组合根首次调用 `get_settings()`，Pydantic Settings 按 `SOMAI_` 前缀读取环境变量并完成校验；
后续调用复用同一实例。

## 依赖关系

本模块的配置能力依赖 Pydantic 与 Pydantic Settings，错误契约只依赖 Python 标准库。
本模块不依赖 API、Application、Agent 或 Provider 模块。

## 数据流

环境变量或 `.env` 文件进入 `Settings`，经校验后由应用组合根注入使用方。
业务模块不直接读取环境变量。
模块内部错误由使用方映射为 `ErrorCode` 和安全消息后跨边界传递。

## 配置说明

必填项为 OpenAI 兼容 API Key 与模型名称，两者都会去除首尾空白并拒绝空值。
基础 URL、生成参数、消息长度及允许来源均在此集中定义。

## 扩展方式

新增全局配置时，应先添加校验测试，再扩展 `Settings` 字段和 `.env.example`；
模块专属配置应保持清晰命名。新增公开错误时，应先确定稳定错误码及安全消息边界，
再扩展 `ErrorCode`。

## 注意事项

不得记录或序列化 API Key 明文。`get_settings()` 的缓存仅适合进程级不可变配置；
测试若修改环境变量，应显式清理缓存。
`SomaiError` 不得保存供应商响应、堆栈或其他内部异常。
