# Admin 模块

## 模块简介

`admin` 管理机器人客户端、访问 Key 和管理员身份认证。数据库模型仅保存可验证的 Key 摘要，不能保存或记录完整 Key。

## 目录说明

- `models.py`：SQLAlchemy 客户端与客户端 Key 表的唯一模型定义。

## 注意事项

- 一个客户端的 Key 轮换必须立即撤销旧 Key。
- 所有 Key 验证和数据库访问由本模块对 API/WebSocket 暴露中立结果。
