# Core 模块

## 模块简介

`core` 提供 SOMAI Chat 中不依赖业务流程的基础能力，当前负责集中式配置管理。

## 主要职责

- 从环境变量和本地 `.env` 文件加载配置。
- 在应用启动前校验运行环境、模型连接参数和输入限制。
- 以敏感类型保存 API Key，避免其出现在对象文本表示中。

## 目录说明

- `config.py`：定义 `Settings` 配置模型和缓存的配置入口。
- `__init__.py`：包标识，不隐式导出实现。

## 核心类

- `Settings`：应用唯一配置模型，提供严格字段约束和安全默认值。

## 核心接口

- `get_settings()`：返回进程内缓存的 `Settings` 实例，供组合根注入其他模块。

## 主要流程

应用组合根首次调用 `get_settings()`，Pydantic Settings 按 `SOMAI_` 前缀读取环境变量并完成校验；后续调用复用同一实例。

## 依赖关系

本模块依赖 Pydantic 与 Pydantic Settings，不依赖 API、Application、Agent 或 Provider 模块。

## 数据流

环境变量或 `.env` 文件进入 `Settings`，经校验后由应用组合根注入使用方。业务模块不直接读取环境变量。

## 配置说明

必填项为 OpenAI 兼容 API Key 与模型名称。基础 URL、生成参数、消息长度及允许来源均在此集中定义。

## 扩展方式

新增全局配置时，应先添加校验测试，再扩展 `Settings` 字段和 `.env.example`；模块专属配置应保持清晰命名。

## 注意事项

不得记录或序列化 API Key 明文。`get_settings()` 的缓存仅适合进程级不可变配置；测试若修改环境变量，应显式清理缓存。
