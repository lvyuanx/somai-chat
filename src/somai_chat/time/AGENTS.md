# Time 模块

## 模块简介

`time` 提供固定为中国标准时间的 LangChain 查询工具，不依赖外部服务。

## 目录说明

- `tool.py`：`create_time_tool(now=None)` 工厂和 `get_current_time` 工具实现。

## 核心接口

`create_time_tool(now=None)` 返回参数为 `days_from_today` 的 `get_current_time` 工具。参数为从当天开始的非负整日偏移：零表示当前时间，一和二分别表示明天和后天。

## 数据流

组合根创建该工具并将其传入 Agent 图。工具将可注入时钟的 UTC 时间转换为 `Asia/Shanghai`，再应用天数偏移，返回日期、星期、时分秒和中国标准时间标识。

## 注意事项

时间工具不读取环境变量，也不提供任意时区、历史时间或提醒功能。负偏移返回稳定错误消息，避免静默提供过去的时间。
