# SOMAI Chat MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-shaped FastAPI and LangGraph service that streams SOMAI conversations over WebSocket and
ships a framework-free browser debugging console.

**Architecture:** A modular monolith exposes health routes, static web assets, and a versioned WebSocket protocol.
The application layer owns one active generation per connection, while a compiled LangGraph and in-memory checkpointer
own conversational state. Provider creation is isolated behind a factory so the graph and tests depend only on the
LangChain chat-model interface.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, LangChain, LangGraph, langchain-openai, Pydantic Settings, HTML/CSS/JS,
pytest, pytest-asyncio, Ruff, mypy, Docker.

---

## Planned File Map

```text
PROJECT_AGENTS.md                         Project-specific architecture and workflow rules
pyproject.toml                            Package metadata, dependencies, lint/type/test configuration
.env.example                             Safe local configuration example
Makefile                                 Development and quality commands
src/somai_chat/main.py                   FastAPI composition root and static console mounting
src/somai_chat/core/config.py            Validated environment-backed settings
src/somai_chat/core/errors.py            Stable application error codes and exception type
src/somai_chat/core/logging.py           Structured logging setup
src/somai_chat/api/protocol.py            Typed WebSocket client events and server-event factory
src/somai_chat/api/health.py              Liveness and readiness endpoints
src/somai_chat/api/websocket.py           Connection receive loop and generation task lifecycle
src/somai_chat/application/conversation.py Streaming Graph adapter and per-connection session controller
src/somai_chat/agent/state.py             LangGraph message state
src/somai_chat/agent/prompts.py           Stable SOMAI system identity
src/somai_chat/agent/graph.py             Graph construction and model node
src/somai_chat/providers/llm.py           OpenAI-compatible chat-model factory
src/somai_chat/web/index.html             Debug console document
src/somai_chat/web/app.css                Responsive industrial-console presentation
src/somai_chat/web/app.js                 WebSocket client and rendering state machine
tests/unit/test_config.py                 Settings behavior
tests/unit/test_protocol.py               Protocol validation and serialization
tests/unit/test_prompts.py                Identity contract
tests/unit/test_graph.py                  Memory and conversation isolation
tests/unit/test_conversation.py           Streaming, failure, busy, and cancellation behavior
tests/integration/test_app.py             Health, static page, and complete WebSocket event flow
Dockerfile                                Non-root runtime image
README.md                                 Setup, configuration, API, and verification guide
```

Every package directory under `src/somai_chat/` also receives an `AGENTS.md` describing its responsibility, public
interfaces, data flow, dependencies, and extension points. Package marker files are empty unless they intentionally
export a public symbol.

### Task 1: Establish the Python Project and Configuration Boundary

**Files:**
- Create: `PROJECT_AGENTS.md`
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `Makefile`
- Create: `src/somai_chat/__init__.py`
- Create: `src/somai_chat/core/__init__.py`
- Create: `src/somai_chat/core/config.py`
- Create: `src/somai_chat/core/AGENTS.md`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Add project constraints and package metadata**

Create `PROJECT_AGENTS.md` with the approved modular-monolith boundaries, Python 3.12 requirement, versioned API rule,
no-secret logging rule, in-memory single-process deployment constraint, TDD workflow, and commands from the Makefile.
Create `pyproject.toml` with this executable configuration:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "somai-chat"
version = "0.1.0"
description = "SOMAI embodied conversational agent runtime"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115,<1",
  "langchain>=1,<2",
  "langchain-openai>=1,<2",
  "langgraph>=1,<2",
  "pydantic-settings>=2.7,<3",
  "uvicorn[standard]>=0.34,<1",
]

[project.optional-dependencies]
dev = [
  "httpx>=0.28,<1",
  "mypy>=1.14,<2",
  "pytest>=8.3,<10",
  "pytest-asyncio>=0.25,<2",
  "ruff>=0.9,<1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/somai_chat"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["somai_chat"]
```

Create `.env.example` with safe values and no real secret:

```dotenv
SOMAI_ENVIRONMENT=development
SOMAI_LOG_LEVEL=INFO
SOMAI_OPENAI_BASE_URL=https://api.openai.com/v1
SOMAI_OPENAI_API_KEY=replace-me
SOMAI_OPENAI_MODEL=replace-with-compatible-model
SOMAI_MODEL_TEMPERATURE=0.4
SOMAI_MODEL_MAX_TOKENS=800
SOMAI_MODEL_TIMEOUT_SECONDS=30
SOMAI_MAX_MESSAGE_LENGTH=8000
SOMAI_ALLOWED_ORIGINS=["http://localhost:8000","http://127.0.0.1:8000"]
```

- [ ] **Step 2: Write the failing configuration tests**

```python
from pydantic import SecretStr, ValidationError
import pytest

from somai_chat.core.config import Settings


def test_settings_accept_openai_compatible_provider() -> None:
    settings = Settings(
        openai_base_url="https://model.example/v1",
        openai_api_key=SecretStr("secret"),
        openai_model="chat-model",
    )

    assert str(settings.openai_base_url).rstrip("/") == "https://model.example/v1"
    assert settings.openai_api_key.get_secret_value() == "secret"
    assert settings.openai_model == "chat-model"


def test_settings_reject_non_positive_message_limit() -> None:
    with pytest.raises(ValidationError):
        Settings(
            openai_api_key=SecretStr("secret"),
            openai_model="chat-model",
            max_message_length=0,
        )


def test_settings_hide_api_key_in_repr() -> None:
    settings = Settings(openai_api_key=SecretStr("top-secret"), openai_model="chat-model")

    assert "top-secret" not in repr(settings)
```

- [ ] **Step 3: Run the tests and verify the missing module failure**

Run: `python -m pytest tests/unit/test_config.py -q`

Expected: collection fails because `somai_chat.core.config` does not exist.

- [ ] **Step 4: Implement validated settings**

```python
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOMAI_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    openai_base_url: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    openai_api_key: SecretStr
    openai_model: str = Field(min_length=1)
    model_temperature: float = Field(default=0.4, ge=0, le=2)
    model_max_tokens: int = Field(default=800, gt=0)
    model_timeout_seconds: float = Field(default=30, gt=0)
    max_message_length: int = Field(default=8000, gt=0)
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- [ ] **Step 5: Add deterministic development commands**

Create a Makefile whose targets are:

```makefile
.PHONY: install dev format lint typecheck test check

install:
	python -m pip install -e '.[dev]'

dev:
	python -m uvicorn somai_chat.main:app --reload --host 0.0.0.0 --port 8000

format:
	python -m ruff format .

lint:
	python -m ruff check .

typecheck:
	python -m mypy

test:
	python -m pytest -q

check: lint typecheck test
```

- [ ] **Step 6: Verify and commit the project foundation**

Run: `python -m pytest tests/unit/test_config.py -q`

Expected: `3 passed`.

Run: `python -m ruff check src/somai_chat/core tests/unit/test_config.py`

Expected: exit code 0.

Commit:

```bash
git add PROJECT_AGENTS.md pyproject.toml .env.example Makefile src/somai_chat tests/unit/test_config.py
git commit -m "build: establish SOMAI Python project"
```

### Task 2: Define Errors and the Versioned WebSocket Protocol

**Files:**
- Create: `src/somai_chat/core/errors.py`
- Create: `src/somai_chat/api/__init__.py`
- Create: `src/somai_chat/api/protocol.py`
- Create: `src/somai_chat/api/AGENTS.md`
- Test: `tests/unit/test_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

```python
import pytest

from somai_chat.api.protocol import MessageCreate, ServerEvent, parse_client_event
from somai_chat.core.errors import ErrorCode, SomaiError


def test_parse_message_create() -> None:
    event = parse_client_event(
        {"type": "message.create", "data": {"message_id": "msg_123", "content": "你好"}},
        max_message_length=20,
    )

    assert isinstance(event, MessageCreate)
    assert event.data.content == "你好"


def test_reject_blank_message() -> None:
    with pytest.raises(SomaiError) as exc_info:
        parse_client_event(
            {"type": "message.create", "data": {"message_id": "msg_123", "content": "  "}},
            max_message_length=20,
        )

    assert exc_info.value.code is ErrorCode.INVALID_MESSAGE


def test_server_event_has_common_envelope() -> None:
    event = ServerEvent.create("response.delta", {"response_id": "resp_1", "delta": "你"})
    payload = event.model_dump(mode="json")

    assert payload["type"] == "response.delta"
    assert payload["event_id"].startswith("evt_")
    assert payload["timestamp"].endswith("Z")
```

- [ ] **Step 2: Run the tests and verify the missing protocol failure**

Run: `python -m pytest tests/unit/test_protocol.py -q`

Expected: collection fails because the protocol module does not exist.

- [ ] **Step 3: Implement stable application errors**

```python
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_MESSAGE = "INVALID_MESSAGE"
    GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
    CANCEL_NOT_FOUND = "CANCEL_NOT_FOUND"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    GENERATION_FAILED = "GENERATION_FAILED"


class SomaiError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
```

- [ ] **Step 4: Implement discriminated client events and server envelopes**

Implement `api/protocol.py` with Pydantic models for `message.create`, `response.cancel`, and `ping`. Use a
discriminated `TypeAdapter`, strip message content, enforce the configured maximum length before returning a
`MessageCreate`, and convert any validation failure to `SomaiError(ErrorCode.INVALID_MESSAGE, "Invalid client event")`.
Use this concrete server-event API:

```python
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ServerEvent(BaseModel):
    type: str
    event_id: str
    timestamp: datetime
    data: dict[str, Any]

    @classmethod
    def create(cls, event_type: str, data: dict[str, Any]) -> "ServerEvent":
        return cls(
            type=event_type,
            event_id=f"evt_{uuid4().hex}",
            timestamp=datetime.now(UTC),
            data=data,
        )
```

- [ ] **Step 5: Verify protocol behavior and commit**

Run: `python -m pytest tests/unit/test_protocol.py -q`

Expected: `3 passed`.

Run: `python -m ruff check src/somai_chat/api src/somai_chat/core/errors.py tests/unit/test_protocol.py`

Expected: exit code 0.

Commit:

```bash
git add src/somai_chat/api src/somai_chat/core tests/unit/test_protocol.py
git commit -m "feat: define WebSocket event protocol"
```

### Task 3: Build the SOMAI Prompt and Stateful LangGraph

**Files:**
- Create: `src/somai_chat/agent/__init__.py`
- Create: `src/somai_chat/agent/state.py`
- Create: `src/somai_chat/agent/prompts.py`
- Create: `src/somai_chat/agent/graph.py`
- Create: `src/somai_chat/agent/AGENTS.md`
- Test: `tests/unit/test_prompts.py`
- Test: `tests/unit/test_graph.py`

- [ ] **Step 1: Write the failing identity contract test**

```python
from somai_chat.agent.prompts import SOMAI_SYSTEM_PROMPT


def test_prompt_defines_identity_and_embodied_boundaries() -> None:
    assert "SOMAI" in SOMAI_SYSTEM_PROMPT
    assert "不要声称已经看见" in SOMAI_SYSTEM_PROMPT
    assert "使用用户当前使用的语言" in SOMAI_SYSTEM_PROMPT
    assert "短句" in SOMAI_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the prompt test and verify it fails**

Run: `python -m pytest tests/unit/test_prompts.py -q`

Expected: collection fails because `somai_chat.agent.prompts` does not exist.

- [ ] **Step 3: Implement the stable SOMAI system prompt**

```python
SOMAI_SYSTEM_PROMPT = """你是 SOMAI，一个运行于 SOMAI 系统中的通用具身智能助手。

你的风格自然、沉稳、友好、简洁。使用用户当前使用的语言回复，优先使用适合语音播放的短句和口语化结构。

你只能依据当前对话和系统明确列出的可用能力回答。没有视觉、位置、设备状态或动作工具时，不要声称已经看见、
感知或执行了现实世界中的操作。用户提出无法执行的动作请求时，清楚说明当前能力边界，并提供语言层面的帮助。

信息不足时明确承认不确定；只有确实影响回答时才提出一个关键澄清问题。拒绝危险或越权操作，并尽可能给出安全替代建议。
被问及身份时，如实说明你是 AI 助手，不冒充真人。

当前可用能力：文本多轮对话。当前没有真实设备、视觉、位置或动作能力。"""
```

- [ ] **Step 4: Write failing graph memory tests with a fake model**

Create a deterministic streaming fake model and test these behaviors through the compiled Graph:

```python
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from somai_chat.agent.graph import build_conversation_graph


@pytest.mark.asyncio
async def test_same_thread_retains_previous_turn() -> None:
    graph = build_conversation_graph(GenericFakeChatModel(messages=iter(["第一轮", "第二轮"])))
    config = {"configurable": {"thread_id": "conversation-a"}}

    await graph.ainvoke({"messages": [("user", "你好")]}, config=config)
    state = await graph.aget_state(config)

    assert [message.content for message in state.values["messages"]][-2:] == ["你好", "第一轮"]


@pytest.mark.asyncio
async def test_different_threads_are_isolated() -> None:
    graph = build_conversation_graph(GenericFakeChatModel(messages=iter(["A回复", "B回复"])))
    await graph.ainvoke(
        {"messages": [("user", "A消息")]},
        config={"configurable": {"thread_id": "conversation-a"}},
    )
    await graph.ainvoke(
        {"messages": [("user", "B消息")]},
        config={"configurable": {"thread_id": "conversation-b"}},
    )

    state_b = await graph.aget_state({"configurable": {"thread_id": "conversation-b"}})

    assert "A消息" not in [message.content for message in state_b.values["messages"]]
```

- [ ] **Step 5: Run the graph tests and verify the missing graph failure**

Run: `python -m pytest tests/unit/test_graph.py -q`

Expected: collection fails because `somai_chat.agent.graph` does not exist.

- [ ] **Step 6: Implement StateGraph with an injected chat model**

Define `ConversationState` as a `TypedDict` containing an `Annotated[list[AnyMessage], add_messages]`. Build a
`StateGraph` with a single async model node that prepends `SystemMessage(SOMAI_SYSTEM_PROMPT)`, invokes the injected
`BaseChatModel`, and returns the AI message. Connect `START -> model -> END` and compile it with an injected checkpointer
or a new `InMemorySaver`. Keep model creation out of this module.

- [ ] **Step 7: Verify graph behavior and commit**

Run: `python -m pytest tests/unit/test_prompts.py tests/unit/test_graph.py -q`

Expected: `3 passed`.

Commit:

```bash
git add src/somai_chat/agent tests/unit/test_prompts.py tests/unit/test_graph.py
git commit -m "feat: add stateful SOMAI conversation graph"
```

### Task 4: Add the Provider Factory and Conversation Session Controller

**Files:**
- Create: `src/somai_chat/providers/__init__.py`
- Create: `src/somai_chat/providers/llm.py`
- Create: `src/somai_chat/providers/AGENTS.md`
- Create: `src/somai_chat/application/__init__.py`
- Create: `src/somai_chat/application/conversation.py`
- Create: `src/somai_chat/application/AGENTS.md`
- Test: `tests/unit/test_conversation.py`

- [ ] **Step 1: Write failing streaming and busy-session tests**

Use a stub Graph whose `astream` yields two `AIMessageChunk` objects. Assert that `ConversationRuntime.stream()` emits
started, two deltas, and completed in order, with one stable response ID and the concatenated final text. Add a delayed
stub and assert `ConversationSession.start()` raises `GENERATION_IN_PROGRESS` when a task is already active.

The core assertion must be:

```python
events = [event async for event in runtime.stream("conv-1", "msg-1", "你好")]

assert [event.type for event in events] == [
    "response.started",
    "response.delta",
    "response.delta",
    "response.completed",
]
assert events[-1].data["content"] == "你好"
assert len({event.data["response_id"] for event in events}) == 1
```

- [ ] **Step 2: Run the tests and verify the missing application failure**

Run: `python -m pytest tests/unit/test_conversation.py -q`

Expected: collection fails because the application module does not exist.

- [ ] **Step 3: Implement OpenAI-compatible model construction**

```python
from langchain_openai import ChatOpenAI

from somai_chat.core.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=str(settings.openai_base_url),
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        temperature=settings.model_temperature,
        max_tokens=settings.model_max_tokens,
        timeout=settings.model_timeout_seconds,
        streaming=True,
    )
```

- [ ] **Step 4: Implement runtime event translation**

`ConversationRuntime.stream(conversation_id, message_id, content)` generates a `resp_` ID, yields
`response.started`, iterates `graph.astream(..., stream_mode="messages")`, filters `AIMessageChunk`, emits non-empty
text as `response.delta`, concatenates text, and yields `response.completed`. Include `usage: null` when the provider
does not expose usage metadata. Map provider failures to
`SomaiError(ErrorCode.GENERATION_FAILED, "Unable to generate a response")` without embedding the original exception in
the client-safe message.

- [ ] **Step 5: Implement one active task and cancellation per connection**

`ConversationSession` owns `active_task`, `active_response_id`, and an async send callback. `start()` creates a task
that pumps runtime events to the callback and clears state in `finally`. `cancel(response_id)` rejects mismatches with
`CANCEL_NOT_FOUND`, cancels and awaits the task, then sends `response.cancelled`. A second `start()` while the task is
active raises `GENERATION_IN_PROGRESS`. `close()` cancels outstanding work without sending on a closed socket.

- [ ] **Step 6: Add cancellation and provider-failure tests, then verify**

Add tests that prove:

- cancelling the active response emits `response.cancelled` and allows the next `start()`;
- cancelling a different ID raises `CANCEL_NOT_FOUND`;
- a Graph exception becomes one `GENERATION_FAILED` error event and the session returns to idle.

Run: `python -m pytest tests/unit/test_conversation.py -q`

Expected: all conversation tests pass.

Commit:

```bash
git add src/somai_chat/providers src/somai_chat/application tests/unit/test_conversation.py
git commit -m "feat: stream and cancel conversation sessions"
```

### Task 5: Expose Health Checks and the WebSocket API

**Files:**
- Create: `src/somai_chat/core/logging.py`
- Create: `src/somai_chat/api/health.py`
- Create: `src/somai_chat/api/websocket.py`
- Create: `src/somai_chat/main.py`
- Test: `tests/integration/test_app.py`

- [ ] **Step 1: Write failing application integration tests**

Build the app through `create_app(runtime=fake_runtime, settings=test_settings)` and test:

```python
def test_health_endpoints(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "alive"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_websocket_streams_ordered_response(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/chat/ws/conv_test") as socket:
        assert socket.receive_json()["type"] == "conversation.ready"
        socket.send_json(
            {"type": "message.create", "data": {"message_id": "msg_test", "content": "你好"}}
        )
        event_types = [socket.receive_json()["type"] for _ in range(4)]

    assert event_types == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.completed",
    ]


def test_invalid_event_returns_error_without_closing(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/chat/ws/conv_test") as socket:
        socket.receive_json()
        socket.send_json({"type": "unknown", "data": {}})
        assert socket.receive_json()["data"]["code"] == "INVALID_MESSAGE"
        socket.send_json({"type": "ping", "data": {"correlation_id": "probe"}})
        assert socket.receive_json()["type"] == "pong"
```

- [ ] **Step 2: Run the integration tests and verify the missing app failure**

Run: `python -m pytest tests/integration/test_app.py -q`

Expected: collection fails because `somai_chat.main` does not exist.

- [ ] **Step 3: Implement health routes and application factory**

Create `/health/live` and `/health/ready` routers. `create_app()` accepts optional settings and runtime dependencies for
tests; production defaults create the OpenAI model, compiled Graph, and runtime exactly once during app composition.
Mount the WebSocket router and keep `app = create_app()` as Uvicorn's import target.

- [ ] **Step 4: Implement the concurrent WebSocket receive loop**

Validate `conversation_id` against `^[A-Za-z0-9_-]{1,128}$` before accepting. Check the Origin against configured
origins. After accept, send `conversation.ready`, construct one `ConversationSession`, and keep receiving while a
generation task runs independently. Dispatch `message.create`, `response.cancel`, and `ping`; map `SomaiError` to an
`error` event. On disconnect, call `session.close()` and never send another event.

- [ ] **Step 5: Implement JSON structured logging without message bodies**

Configure the standard library logger once at startup. Log lifecycle and failures with IDs and error code in `extra`.
Do not pass message content, model output, API keys, or raw provider response bodies into log fields.

- [ ] **Step 6: Verify HTTP and WebSocket behavior and commit**

Run: `python -m pytest tests/integration/test_app.py -q`

Expected: health, ordered stream, recoverable protocol error, ping/pong, busy, and cancel tests pass.

Run: `python -m ruff check src tests`

Expected: exit code 0.

Commit:

```bash
git add src/somai_chat/core src/somai_chat/api src/somai_chat/main.py tests/integration
git commit -m "feat: expose SOMAI WebSocket service"
```

### Task 6: Build the Framework-Free Debug Console

**Files:**
- Create: `src/somai_chat/web/index.html`
- Create: `src/somai_chat/web/app.css`
- Create: `src/somai_chat/web/app.js`
- Create: `src/somai_chat/web/AGENTS.md`
- Modify: `src/somai_chat/main.py`
- Modify: `tests/integration/test_app.py`

- [ ] **Step 1: Add failing static-console tests**

```python
def test_debug_console_is_served(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "SOMAI" in response.text
    assert 'id="message-input"' in response.text


def test_debug_console_assets_are_served(client: TestClient) -> None:
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
```

- [ ] **Step 2: Run the tests and verify the missing static route failure**

Run: `python -m pytest tests/integration/test_app.py -k debug_console -q`

Expected: both tests fail with HTTP 404.

- [ ] **Step 3: Implement the accessible console document**

Create semantic HTML with three regions: session metadata, `aria-live="polite"` message timeline, and event trace.
Include a labeled textarea with `id="message-input"`, send/stop button, new-session button, clear-display button, and a
connection status element. Load `/assets/app.css` and `/assets/app.js` without third-party CDN dependencies.

- [ ] **Step 4: Implement the approved industrial-console styling**

Use local fallback font stacks, CSS custom properties for warm paper, ink, signal orange, success green, and borders.
Implement the three-column desktop layout, distinct user/SOMAI messages, streaming cursor, visible keyboard focus,
reduced-motion support, and a mobile breakpoint that hides side rails while preserving the conversation.

- [ ] **Step 5: Implement the browser WebSocket state machine**

Generate or restore `conversation_id` from `localStorage`. Derive `ws://` or `wss://` from `window.location`, render
every received event in the trace, append deltas to one active assistant message, and finalize on completed/cancelled.
Enter sends, Shift+Enter inserts a newline. During generation the primary button sends `response.cancel`; it never sends
a second message. Unexpected disconnects use capped exponential reconnect delays and never replay the last message.
Render Markdown with a small DOM-building renderer that supports paragraphs, headings, lists, fenced code, inline code,
and `http(s)` links. Create nodes and assign textual content with `textContent`; never insert model output through
`innerHTML`, so Markdown support cannot become HTML injection.

- [ ] **Step 6: Mount assets, verify, and commit**

Mount `/assets` with `StaticFiles` and return `index.html` from `/`. Resolve paths with `importlib.resources` or a path
derived from the installed package, not the current working directory.

Run: `python -m pytest tests/integration/test_app.py -q`

Expected: all application and console tests pass.

Commit:

```bash
git add src/somai_chat/web src/somai_chat/main.py tests/integration/test_app.py
git commit -m "feat: add SOMAI conversation console"
```

### Task 7: Package, Document, and Verify the Deliverable

**Files:**
- Create: `Dockerfile`
- Modify: `README.md`
- Create: `src/somai_chat/AGENTS.md`
- Modify: all module `AGENTS.md` files if implementation details changed during Tasks 1–6

- [ ] **Step 1: Add a non-root production container**

```dockerfile
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN addgroup --system somai && adduser --system --ingroup somai somai

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install .

USER somai
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "somai_chat.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Replace the README with an operational guide**

Document the product boundary, architecture, Python 3.12 setup, `cp .env.example .env`, `make install`, `make dev`,
the browser URL, all environment variables, WebSocket event examples, quality commands, Docker build/run commands,
single-process memory limitation, and extension points for persistent checkpointers and tools.

- [ ] **Step 3: Reconcile module documentation with the finished code**

For every functional module, confirm its `AGENTS.md` accurately names the public classes/functions, input/output flow,
dependencies, configuration, extension points, and the in-memory/cancellation caveats. Remove any description of a class
or event that was not implemented.

- [ ] **Step 4: Run the complete local quality gate**

Run: `python -m ruff format --check .`

Expected: exit code 0 and no files requiring formatting.

Run: `python -m ruff check .`

Expected: exit code 0 with no lint errors.

Run: `python -m mypy`

Expected: exit code 0 with no type errors.

Run: `python -m pytest -q`

Expected: exit code 0 with all unit and integration tests passing.

- [ ] **Step 5: Verify the production artifact**

Run: `docker build -t somai-chat:mvp .`

Expected: image builds successfully.

Run: `docker run --rm --entrypoint id somai-chat:mvp`

Expected: output identifies the non-root `somai` user.

- [ ] **Step 6: Review scope and commit the delivery files**

Run: `git status --short`

Expected: only Docker, README, and module-documentation changes from this task are present; the user's untracked root
`AGENTS.md` remains unstaged unless the user explicitly asks to commit it.

Commit:

```bash
git add Dockerfile README.md PROJECT_AGENTS.md src/somai_chat/AGENTS.md src/somai_chat/*/AGENTS.md
git commit -m "docs: add SOMAI operations and deployment guide"
```

## Final Acceptance Walkthrough

- [ ] Start the service with a valid OpenAI-compatible `.env` and open `http://localhost:8000`.
- [ ] Send two related messages under one conversation ID and confirm the second reply uses prior context.
- [ ] Create a new conversation and confirm it has no access to the previous conversation.
- [ ] Stop a long response from the console and confirm a new message can be sent afterward.
- [ ] Send an invalid event using a WebSocket client and confirm the connection remains usable after `INVALID_MESSAGE`.
- [ ] Inspect application logs and confirm correlation IDs exist while prompts, replies, and the API key do not.
- [ ] Re-run `make check` immediately before reporting completion.
