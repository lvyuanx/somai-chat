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
服务重启会丢失全部对话状态。生产容器必须以非 root 用户运行，并通过 `python -m somai_chat.main` 启动，确保监听配置和 WebSocket 帧上限来自同一 Settings。

## API 与日志契约

- 健康检查为 `/health/live` 与 `/health/ready`；就绪探针不得调用外部模型。
- 对话地址为 `/api/v1/chat/ws/{conversation_id}`，事件使用 `type/event_id/timestamp/data` 统一信封。
- 浏览器 Origin 必须匹配集中配置；设备客户端可以不发送 Origin；文本同时受字符数和 UTF-8 帧字节限制。
- 日志只允许固定消息、connection/conversation/message/response ID 与稳定错误码，不记录正文、回复、密钥或供应商原始错误。

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
- `node tests/js/web_console_state.mjs` 与 `node tests/js/console_view.mjs`：验证浏览器协议状态机与有界视图。
- `uv build`：构建包含调试台静态资源的 wheel 与 sdist。
- `docker build -t somai-chat:mvp .`：构建 Python 3.12 slim 非 root 生产镜像。
