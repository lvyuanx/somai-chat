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
- `app.js`：连接状态机、协议事件处理、安全 Markdown 与页面交互。
- `__init__.py`：包标识，使静态资源随 Python 包分发。

## 主要流程与数据流

页面从 `localStorage` 恢复或生成 `conv_` 前缀 ASCII 会话 ID，根据当前页面协议选择 `ws`/`wss`。
收到 `conversation.ready` 后启用发送；started 创建回复气泡，delta 增量重绘安全 Markdown，
completed、cancelled
或 error 结束当前生成。生成期间主按钮只发送 `response.cancel`，不会创建第二条消息。

意外断线使用最多五次指数退避重连，不重放上一次消息。
新建会话主动关闭旧连接、清空本地视图并连接新 ID；
清空显示仅删除消息与轨迹 DOM。页面卸载时主动关闭连接。

## 安全与扩展方式

Markdown 仅支持段落、一级至三级标题、列表、围栏代码、行内代码和 HTTP(S) 链接。
所有用户、模型与事件内容通过 `textContent` 或文本节点写入；
链接协议通过 `URL` 再校验，并带 `noopener noreferrer`。
新增协议事件时应在 `handleEvent` 中显式处理，未知事件只保留在受限轨迹中。

## 注意事项

- 页面必须在模型配置缺失时仍能访问；只有 WebSocket 运行时会处于未就绪状态。
- 资源路径由 Python 包位置解析，不能依赖服务启动时的当前工作目录。
- 页面不加载外部字体、脚本、样式或 CDN 资源。
