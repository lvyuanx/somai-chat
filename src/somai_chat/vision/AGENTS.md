# Vision 模块

`vision` 将远程图片转换为 Qwen3-VL-Plus 可理解的 data URL，并返回带不可信标记的文本观察结果。
`fetcher.py` 限制响应类型、重定向与下载字节数；`analyzer.py` 不生成最终用户回复，只供 Application 注入主对话模型。
该模块不得记录图片 URL、图片字节或视觉结果。
