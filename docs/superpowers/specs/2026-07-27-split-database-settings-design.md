# 拆分数据库配置设计

## 目标

将单一的 `SOMAI_DATABASE_URL` 替换为可读、可独立配置的 MySQL 连接字段，降低本地部署时填写连接字符串的难度，
并避免密码中特殊字符破坏 URL 解析。

## 配置契约

新增以下环境变量：

```dotenv
SOMAI_DATABASE_USER=somai
SOMAI_DATABASE_PASSWORD=change-me
SOMAI_DATABASE_HOST=127.0.0.1
SOMAI_DATABASE_PORT=3306
SOMAI_DATABASE_NAME=somai
```

`SOMAI_HOST` 和 `SOMAI_PORT` 继续只表示 Uvicorn Web 服务的监听地址和端口。数据库字段必须使用
`SOMAI_DATABASE_` 前缀，避免同名配置承担两种含义。

现有 `SOMAI_DATABASE_URL` 完全移除，不提供优先级或兼容兜底。升级时需要将原 URL 拆分为上述五个字段。

## 默认值与校验

- 用户名默认 `somai`，不能为空。
- 密码默认 `change-me`，使用 `SecretStr`，不能为空。
- Host 默认 `127.0.0.1`，不能为空。
- Port 默认 `3306`，范围为 1–65535。
- 数据库名默认 `somai`，不能为空。
- 生产环境拒绝 `change-me`、`replace`、`your-secret` 等占位数据库密码。

数据库密码不得出现在 Settings 的 `repr`、应用日志或公开错误中。

## URL 构建与数据流

`Settings` 提供只读的数据库连接 URL 构建入口。实现使用 SQLAlchemy `URL.create()`，由库负责正确处理用户名、密码、
IPv6 Host 及 `@`、`:`、`/`、`#` 等特殊字符。业务代码不得自行拼接数据库 URL。

应用组合根通过该入口取得 `mysql+asyncmy` URL，并注入 `create_session_factory`。Alembic `env.py` 同样加载
`Settings` 并调用相同入口，使迁移命令与应用运行使用完全一致的数据库连接配置。

URL 只在传给 SQLAlchemy/Alembic 时以包含密码的形式渲染；不写入日志。对外文档只展示占位密码。

## 影响范围

- `core/config.py`：新增五个字段、校验和集中 URL 构建入口，删除 `database_url`。
- `main.py`：改用集中构建入口创建数据库会话工厂。
- `alembic/env.py`：改用同一 Settings 配置，不再直接读取 `SOMAI_DATABASE_URL`。
- `.env.example` 与 `README.md`：替换环境变量和迁移示例，说明 Web 与数据库 Host/Port 的区别。
- Core、Admin 和组合根模块 `AGENTS.md`：同步配置来源与数据流。
- 现有测试与生产配置样例：迁移到拆分字段。

## 测试策略

实现遵循 TDD：

- 先验证默认拆分字段和自定义字段。
- 验证密码在 `repr` 中不可见。
- 验证特殊字符密码通过 `URL.create()` 正确往返。
- 验证空用户名、密码、Host、数据库名和非法端口被拒绝。
- 验证生产环境拒绝占位数据库密码。
- 验证应用组合根把生成的 URL 传给数据库工厂。
- 验证 Alembic 使用拆分配置，且仓库中不再引用 `SOMAI_DATABASE_URL`。
- 最后运行 Ruff、严格 mypy、完整 pytest 和现有前端测试。
