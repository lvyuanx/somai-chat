# 管理后台前端

## 模块简介

此模块是 SOMAI 具身智能机器人后台的 Vue 3 单页应用，使用 Element Plus 组件库构建。Vite 将产物输出到
`src/somai_chat/admin_web/dist`，由 FastAPI 在 `/admin` 提供服务。

## 主要职责

- 管理员登录与会话恢复。
- 以卡片展示机器人客户端的在线状态，并用开关启停客户端、轮换连接 WebSocket 的 Key。
- 默认展示脱敏 Key；管理员通过眼睛图标短暂查看后才可复制完整 Key，旧 Key 则引导轮换。
- 提供内嵌的 Chat 工作区；该视图使用同源 iframe 加载现有调试台，保留其完整会话、图片和事件追踪能力。

## 目录说明

- `src/App.vue`：后台壳、Element Plus 视图、管理员 API 调用和客户端管理交互。
- `src/main.js`：Vue 与 Element Plus 应用入口。
- `src/style.css`：深色科技风的后台主题覆盖。
- `src/client-cards.css`：客户端卡片、在线状态、Key 脱敏与查看控件样式。
- `vite.config.js`：将生产资源写入 Python 包的静态目录。

## 数据流

浏览器请求 `/api/v1/admin/session` 建立 Cookie 会话并获取 CSRF Token；后续客户端管理请求携带该 Token。Chat
工作区不复制协议实现，而是加载 `/assets/index.html?embed=1`，由原调试台直接连接版本化 WebSocket。

## 构建与注意事项

在本目录运行 `npm run build` 更新包内静态资源。不得使用 CDN：生产资源必须完整打包，以满足应用 CSP。变更导航
时保持 Chat 工作区在后台壳内，不能以顶层导航替代 iframe。
