# Loguru 日志重构设计

## 目标

使用 Loguru 统一 SOMAI Chat 的应用日志和标准库/依赖日志，同时保留项目现有的安全边界：不记录 API Key、用户正文、模型回复或供应商原始异常；应用日志仍按 `source="project"` 路由到项目专属输出。

## 方案

- 在 `somai_chat.core.logging` 中集中配置 Loguru sink、级别颜色和标准库 `logging` 拦截器。
- 配置输出到按日期命名的全量日志、项目日志和错误日志；项目日志同时输出到控制台。
- `setup_logging`/`configure_logging` 对相同目录和级别幂等，重新配置时先移除已有 Loguru sink，避免重复输出。
- `get_logger()` 返回绑定 `source="project"` 的 Loguru logger，组合根和 WebSocket 迁移到该入口。
- 标准库拦截器仅接管应用及明确的依赖 logger，不强制覆盖 root/Uvicorn 运维 handler；已有标准库调用仍可被转发。
- 保留 `JsonFormatter` 兼容测试和外部调用，使用允许的关联字段生成安全 JSON。

## 配置与数据流

`Settings.log_level` 继续提供默认级别，并新增日志目录配置。组合根在 lifespan 中调用日志配置；业务模块只通过 `get_logger()` 写入固定消息和关联 ID。标准库记录经拦截器转换为 Loguru 记录后进入全量/错误 sink，项目记录因绑定字段额外进入项目 sink 和控制台 sink。

## 错误处理与安全

- 日志目录自动创建；文件使用 UTF-8 编码。
- 未知标准库级别降级为数值级别，保留异常信息用于 Loguru 内部格式化，但不把动态异常文本写入应用固定消息。
- 过滤器只依据 `source` 路由，不序列化任意 `extra` 字段。

## 测试

测试覆盖幂等配置、项目/全量/错误/控制台路由、标准库记录拦截、未知级别处理，以及敏感字段不会出现在 JSON 兼容格式中。完整测试套件、Ruff 和 mypy 作为提交前验证。
