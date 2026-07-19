# Admin 模块

## 模块简介

`admin` 管理机器人客户端、访问 Key 和管理员身份认证。数据库保存 Key 摘要用于认证，并对新 Key 保存可管理员查看的
认证加密密文；日志不能记录完整 Key。

## 目录说明

- `models.py`：SQLAlchemy 客户端与客户端 Key 表的唯一模型定义。
- `credentials.py`：生成 Key、计算认证摘要，以及使用独立配置密钥对完整 Key 加密与解密。
- `presence.py`：进程内 WebSocket 连接注册表；每个客户端最多只能有一条通过 Key 认证的连接。

## 注意事项

- 一个客户端的 Key 轮换必须立即撤销旧 Key。
- 所有 Key 验证和数据库访问由本模块对 API/WebSocket 暴露中立结果。
- `encrypted_key` 为可空字段，兼容旧数据；旧 Key 没有密文，必须轮换后才能被管理员查看或复制。
- `SOMAI_CLIENT_KEY_ENCRYPTION_SECRET` 必须与校验 pepper 分开管理，生产环境不得使用占位值。
- 在线状态仅代表当前进程中的唯一活跃连接，符合项目的单进程部署边界，不持久化到 MySQL；新连接会以 `4001`
  关闭码顶掉旧连接，设备功能必须复用当前连接并以消息码区分。
