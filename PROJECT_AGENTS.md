# SOMAI Chat 项目约束

## 架构边界

本项目采用模块化单体架构。FastAPI 进程统一提供版本化 API、LangGraph 对话编排和调试页面，各模块通过清晰的公开接口协作，不跨层直接访问实现细节。

## 技术与接口

- 运行时统一使用 Python 3.12。
- 对外 API 必须带版本前缀，例如 `/api/v1`；不兼容变更通过新版本发布。
- 配置集中在 `core` 模块，业务模块不得直接读取环境变量。
- 模型供应商通过 OpenAI 兼容接口接入，业务层不得绑定具体供应商实现。

## 安全与日志

- 不得提交真实 API Key、令牌或其他凭据。
- 日志不得记录 API Key、完整用户消息或完整模型回复。
- 对外错误只返回稳定错误码和安全信息，不暴露堆栈或供应商原始响应。

## 会话与部署

MVP 使用进程内 Checkpointer 和会话并发控制，仅支持单进程部署。引入共享状态基础设施前，不得直接进行多进程或多实例横向扩容。

## 开发流程

所有功能与缺陷修复遵循 TDD：先添加并观察失败测试，再以最小实现使其通过，最后在绿灯下重构。代码变更必须同步维护最近模块的 `AGENTS.md`。

## 质量命令

- `make install`：创建并安装开发环境。
- `make dev`：通过 `python -m somai_chat.main` 启动本地开发服务；监听地址、端口、reload 模式与
  WebSocket 帧上限均来自同一个 `Settings` 实例。
- `make format`：格式化代码。
- `make lint`：运行 Ruff 静态检查。
- `make typecheck`：运行严格 mypy 检查。
- `make test`：运行测试。
- `make check`：依次运行 lint、typecheck 和 test。
