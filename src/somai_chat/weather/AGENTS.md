# Weather 模块

## 模块简介

`weather` 封装和风天气的 GeoAPI、实时天气和逐日预报接口，为 Agent 工具提供稳定、最小化的天气数据。

## 主要职责

- 将城市名称解析为经纬度。
- 查询当前气温、体感温度、天气现象和风速，以及指定日期的逐日预报。
- 解析昨天、今天、明天和 `YYYY年M月D日` 日期表达式。
- 将和风天气响应归一为不含供应商实现细节的结构化数据。
- 用户未指定城市时，默认查询武汉。

## 目录说明

- `client.py`：`QWeatherClient`，只依赖注入的 `httpx.AsyncClient`。
- `tool.py`：将客户端封装为 `get_weather(city, date)` LangChain 工具，并将可预期日期边界和上游故障转换为稳定提示。

## 核心接口与数据流

`QWeatherClient.get_weather(city=None, date_text=None)` 先解析日期。未指定日期或今天调用现有的
`get_current_weather`，它会先调用 GeoAPI `/geo/v2/city/lookup`，再使用结果的 LocationID 调用 `/v7/weather/now`。
未来日期调用同一地点解析流程后访问 `/v7/weather/3d` 并选择匹配的 `fxDate`。请求通过 `X-QW-Api-Key` 鉴权；城市为空时使用
`DEFAULT_CITY`（武汉）。
`create_weather_tool(client)` 创建可选 `city` 和 `date` 参数的 `get_weather` 工具，供 Agent 绑定到模型。昨天、过去日期、格式
无效日期及供应商预报窗口外日期返回“该日期暂无可查询天气数据”；网络、HTTP 或供应商数据异常仍返回安全的服务不可用提示。

## 依赖与注意事项

本模块不读取环境变量、不管理 HTTP 客户端生命周期、不写日志。组合根负责从 `Settings` 注入服务地址、超时和
客户端，并负责关闭客户端。上游网络、HTTP 或数据格式异常交由 Agent 工具转换为安全用户提示，不暴露 URL 或原始响应。
