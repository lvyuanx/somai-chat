# Web 模块

## 模块简介

`web` 是无前端构建步骤的 SOMAI 调试运行台，只使用浏览器原生 HTML、CSS、DOM 与 WebSocket API。

## 主要职责

- 展示会话连接、模型标识、对话消息与有上限的协议事件轨迹。
- 通过公开 `/api/v1/chat/ws/{conversation_id}` 协议发送消息、停止生成和恢复连接。
- 使用安全的 DOM Markdown 子集渲染流式回复，不解释模型或用户提供的 HTML。
- 将合法会话 ID 保存在浏览器本地；新建会话时更换 ID，清空显示时不改变服务端状态。

## 目录说明

- `index.html`：三栏语义结构、表单与可访问性标记。
- `app.css`：工业设备控制台视觉、消息状态、响应式布局和减少动效规则。
- `app.js`：连接状态机、动态输入限额、流式渲染调度与页面交互。
- `markdown.js`：只通过 DOM 文本 API 构建允许的安全 Markdown 子集。
- `package.json`：把同目录 JavaScript 声明为原生 ES module，供浏览器与 Node 检查使用。
- `__init__.py`：包标识，使静态资源随 Python 包分发。

## 主要流程与数据流

页面从 `localStorage` 恢复或生成 `conv_` 前缀 ASCII 会话 ID，根据当前页面协议选择 `ws`/`wss`。
收到 `conversation.ready` 后启用发送。
ready 同时提供消息 code point 上限和 WebSocket 帧字节上限；
页面按 code point 计数，发送前对最终
JSON envelope 使用 `TextEncoder` 复核帧字节数。非法或缺失的服务端上限回退到安全默认值。
消息成功写入 WebSocket 后立即从 idle 进入 pending，禁止在 started
返回前重复发送；匹配 pending message ID 的 started 使状态进入 streaming 并创建回复气泡。
delta、completed、cancelled 与 error 只有关联当前 message/response ID 时才能更新或结束当前请求。
streaming 状态下主按钮只发送一次 `response.cancel`，
成功写入后立即进入 cancelling 并禁用按钮，
直到匹配的终态事件到达。

意外断线使用最多五次指数退避重连，不重放上一次消息；
任何非 idle 请求会清理并显示未重放提示。
每个 socket 回调先确认自己仍是当前连接，旧连接的迟到事件不得改变新会话 UI。
新建会话主动关闭旧连接、清空本地视图并连接新 ID；
清空显示仅在 idle 时删除消息与轨迹 DOM，活跃请求期间按钮和处理器都禁止该操作。
页面卸载时主动关闭连接。

delta 只累加有界文本，并用 `requestAnimationFrame` 合并同帧重绘；
终态同步取消并刷新待处理帧。
单条回复最多展示 100,000 code points，timeline 最多 100 条消息，trace 最多 120 条事件且单条 JSON
最多展示 12,000 code points，达到上限时显示截断标记并丢弃超出内容。

桌面使用三栏运行台；
850px 及以下保留紧凑 session rail、连接状态与会话操作，隐藏品牌细节、
会话/模型详情和 trace rail。独立隐藏 live region 只播报 ready、终态和错误，不播报 delta。

## 安全与扩展方式

Markdown 仅支持段落、一级至三级标题、列表、围栏代码、行内代码和 HTTP(S) 链接。
所有用户、模型与事件内容通过 `textContent` 或文本节点写入；
链接协议通过 `URL` 再校验，并带 `noopener noreferrer`。
新增协议事件时应在 `handleEvent` 中显式处理，未知事件只保留在受限轨迹中。

## 注意事项

- 页面必须在模型配置缺失时仍能访问；只有 WebSocket 运行时会处于未就绪状态。
- 资源路径由 Python 包位置解析，不能依赖服务启动时的当前工作目录。
- 页面不加载外部字体、脚本、样式或 CDN 资源。
- HTTP 响应通过应用中间件设置 CSP、`nosniff` 和未指纹页面/资源的 `no-cache`。
