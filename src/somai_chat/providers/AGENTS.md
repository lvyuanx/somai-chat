# Providers 模块

## 模块简介

`providers` 封装 SOMAI Chat 使用的外部模型客户端创建逻辑，使业务层不绑定具体供应商。

## 主要职责

- 将集中式配置映射为 OpenAI 兼容的流式聊天模型。
- 保持 API Key 为敏感类型，不在日志或对象表示中暴露明文。

## 目录说明

- `llm.py`：提供 OpenAI 兼容聊天模型工厂。
- `__init__.py`：包标识，不隐式创建外部客户端。

## 核心接口与流程

`create_chat_model(settings)` 接收组合根注入的 `Settings`，创建启用流式输出的 `ChatOpenAI`。
它映射基础 URL、API Key、模型名、温度、最大输出、超时配置，不发起网络请求。

## 依赖关系与数据流

本模块依赖 `core.config` 与 `langchain-openai`，不依赖 Application、Agent 或 API。
配置由组合根传入工厂，产出的 `BaseChatModel` 随后注入 Agent Graph。

## 扩展方式与注意事项

新增供应商时应优先保持 OpenAI 兼容配置；确需专用适配器时，
应提供相同的 LangChain 模型接口。
不得直接读取环境变量，不得记录、转换为普通字符串或序列化 API Key，
也不得在工厂中进行连通性请求。
