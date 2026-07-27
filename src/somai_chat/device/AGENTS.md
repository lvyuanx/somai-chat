# Device 模块

## 模块简介

`device` 定义由对话模型发起、由端侧设备执行的受控能力请求。

## 主要职责

- 提供 `camera_capture` 模型工具。
- 将模型工具结果编码为受信任的内部动作数据。
- 不直接访问摄像头、网络或端侧设备。

## 核心接口

- `create_camera_capture_tool()`：创建绑定到对话模型的摄像头请求工具。
- `parse_camera_capture_result(content)`：严格解析摄像头工具结果。

工具调用结束当前对话轮后，由 Application 转换为 `action.request` 事件发送给端侧；端侧上传图片后，使用
`message.create` 携带 `image_ids` 开启下一轮视觉分析。
如果端侧无法拍摄，应回传 `action.result`，服务端会根据 `status` 和 `error_code` 回复用户原因；不得只发送未知事件。

## 注意事项

动作请求只描述一次拍摄，不包含图片内容或设备私密信息。模块不得记录用户消息、图片或客户端凭据。
