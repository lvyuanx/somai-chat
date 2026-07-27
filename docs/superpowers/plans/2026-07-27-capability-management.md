# Admin Dynamic Capability Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Admin capability-management page that persists, reveals, enables, disables, and hot-reloads weather, time, and web-search capabilities without restarting SOMAI or losing conversation history.

**Architecture:** Store one validated row per managed capability and publish immutable in-memory tool snapshots through a `CapabilityService`. `ConversationRuntime` captures one snapshot per message and passes it to a dynamically bound LangGraph, so an active turn remains stable while the next turn sees saved changes. The Vue Admin page edits one fixed-schema capability card at a time and never receives secret values through list responses.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, Alembic/MySQL, LangGraph/LangChain, httpx, Vue 3, Element Plus, Vite, pytest, Node.js assertions.

---

## File map

- `alembic/versions/0003_add_capabilities.py`: create the capability persistence table.
- `src/somai_chat/admin/models.py`: add the `Capability` SQLAlchemy model.
- `src/somai_chat/admin/capability_repository.py`: isolate capability row seeding, listing, and locked updates.
- `src/somai_chat/capabilities/models.py`: fixed schemas, stored-state DTOs, public views, update commands, and snapshots.
- `src/somai_chat/capabilities/service.py`: validate updates, encrypt/reveal secrets, build tools, and atomically publish snapshots.
- `src/somai_chat/capabilities/AGENTS.md`: document the new module and its data flow.
- `src/somai_chat/application/conversation.py`: capture one capability snapshot per turn.
- `src/somai_chat/agent/graph.py`: bind and execute the per-turn tool set while preserving the existing graph/checkpointer.
- `src/somai_chat/api/capabilities.py`: expose list, save, and secret-reveal endpoints.
- `src/somai_chat/main.py`: seed the service, own shared HTTP clients, and inject the snapshot provider.
- `src/somai_chat/weather/client.py`: apply snapshot-specific request timeouts.
- `src/somai_chat/web/search.py`: accept snapshot-specific API host and timeout without owning a connection pool.
- `frontend/admin/src/capability-state.js`: pure draft/payload transformations for browser tests.
- `frontend/admin/src/CapabilityManagement.vue`: capability cards and API interactions.
- `frontend/admin/src/ClientManagement.vue`: extract the existing client-card page so `App.vue` returns below 500 lines.
- `frontend/admin/src/capability-cards.css`: capability layout, states, and responsive rules.
- `frontend/admin/src/App.vue`: add navigation and compose the extracted pages.
- `tests/js/admin_capability_state.mjs`: test secret-preserving payload construction and validation.
- `tests/unit/test_capability_service.py`: test seeding, validation, encryption, and snapshots.
- `tests/unit/test_capability_api.py`: test Admin authentication/CSRF and safe API shapes.
- Existing tests and module `AGENTS.md` files listed in the tasks below: extend regression coverage and documentation.

### Task 1: Persist capability rows and validate the encryption setting

**Files:**
- Create: `alembic/versions/0003_add_capabilities.py`
- Modify: `src/somai_chat/admin/models.py`
- Modify: `src/somai_chat/core/config.py`
- Modify: `.env.example`
- Test: `tests/unit/test_admin_models.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing model and settings tests**

Add tests that express the new schema and secret contract:

```python
def test_capability_schema_keeps_sensitive_values_out_of_configuration() -> None:
    assert set(Base.metadata.tables) == {"clients", "client_access_keys", "capabilities"}
    columns = Base.metadata.tables["capabilities"].c

    assert {"key", "enabled", "configuration", "encrypted_api_key", "created_at", "updated_at"} <= set(columns)
    assert "api_key" not in columns


def test_settings_hides_capability_encryption_secret() -> None:
    settings = Settings(
        openai_api_key="chat-secret",
        openai_model="chat-model",
        capability_secret_encryption_secret="capability-secret",
    )

    assert settings.capability_secret_encryption_secret.get_secret_value() == "capability-secret"
    assert "capability-secret" not in repr(settings)


def test_production_rejects_placeholder_capability_encryption_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            openai_api_key="chat-secret",
            openai_model="chat-model",
            database_url="mysql+asyncmy://somai:pass@db:3306/somai",
            admin_password="strong-password",
            admin_session_secret="production-session-secret",
            client_key_pepper="production-pepper",
            client_key_encryption_secret="production-client-encryption",
            capability_secret_encryption_secret="change-me",
        )
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_admin_models.py tests/unit/test_config.py -q
```

Expected: failures because the `capabilities` table and `capability_secret_encryption_secret` setting do not exist.

- [ ] **Step 3: Add the model, migration, and setting**

Add this model to `admin/models.py`:

```python
from sqlalchemy import JSON


class Capability(Base):
    __tablename__ = "capabilities"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="0")
    configuration: Mapped[dict[str, object]] = mapped_column(JSON(), nullable=False)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

Create revision `0003` with `down_revision = "0002"` and an `upgrade()` that creates those exact columns. Its `downgrade()` drops only `capabilities`.

Add the setting and include it in administrator-secret validation and production placeholder checks:

```python
capability_secret_encryption_secret: SecretStr = SecretStr("change-me")
```

Add this documented sample value to `.env.example`:

```dotenv
SOMAI_CAPABILITY_SECRET_ENCRYPTION_SECRET=replace-with-a-dedicated-random-secret
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit the persistence foundation**

```bash
git add alembic/versions/0003_add_capabilities.py .env.example \
  src/somai_chat/admin/models.py src/somai_chat/core/config.py \
  tests/unit/test_admin_models.py tests/unit/test_config.py
git commit -m "feat(admin): persist capability settings"
```

### Task 2: Build the fixed-schema capability service

**Files:**
- Create: `src/somai_chat/capabilities/__init__.py`
- Create: `src/somai_chat/capabilities/models.py`
- Create: `src/somai_chat/capabilities/service.py`
- Create: `src/somai_chat/capabilities/AGENTS.md`
- Create: `src/somai_chat/admin/capability_repository.py`
- Test: `tests/unit/test_capability_service.py`

- [ ] **Step 1: Write failing service tests with a fake repository**

Define an in-memory repository stub and cover these behaviors with separate tests:

```python
@pytest.mark.asyncio
async def test_initialization_seeds_only_missing_capabilities() -> None:
    repository = MemoryCapabilityRepository(existing={"time": stored_time(enabled=False)})
    service = make_service(repository)

    await service.initialize(default_seeds())

    assert repository.seeded_keys == {"weather", "web_search"}
    views = {view.key: view for view in await service.list_views()}
    assert views["time"].enabled is False


@pytest.mark.asyncio
async def test_enabled_weather_requires_an_api_key() -> None:
    service = await initialized_service(weather_api_key=None)

    with pytest.raises(CapabilityValidationError, match="API Key"):
        await service.update(
            "weather",
            CapabilityUpdate(enabled=True, configuration=weather_configuration()),
        )


@pytest.mark.asyncio
async def test_update_preserves_replaces_and_clears_api_key() -> None:
    service = await initialized_service(weather_api_key="weather-old")

    preserved = await service.update("weather", weather_update(enabled=True))
    replaced = await service.update("weather", weather_update(enabled=True, api_key="weather-new"))
    cleared = await service.update("weather", weather_update(enabled=False, clear_api_key=True))

    assert preserved.api_key_masked.endswith("-old")
    assert await service.reveal_api_key("weather") == "weather-new"
    assert replaced.can_reveal_api_key is True
    assert cleared.api_key_masked is None


@pytest.mark.asyncio
async def test_snapshot_contains_only_enabled_tools() -> None:
    service = await initialized_service(weather_enabled=True, time_enabled=False, search_enabled=True)

    assert {tool.name for tool in service.snapshot()} == {"get_weather", "web_search"}


@pytest.mark.asyncio
async def test_invalid_ciphertext_does_not_expose_or_publish_the_capability() -> None:
    service = await initialized_service(weather_ciphertext="not-valid-fernet")

    assert "get_weather" not in {tool.name for tool in service.snapshot()}
    with pytest.raises(CapabilitySecretUnavailableError):
        await service.reveal_api_key("weather")
```

The fake repository must store ciphertext, assert that neither plaintext API Key appears in `configuration`, and return detached DTOs rather than SQLAlchemy objects.

- [ ] **Step 2: Run the service test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_capability_service.py -q
```

Expected: import failure because the capability module and repository contract do not exist.

- [ ] **Step 3: Implement fixed models and DTOs**

In `capabilities/models.py`, define the exact supported key and strict configurations:

```python
type CapabilityKey = Literal["weather", "time", "web_search"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WeatherConfiguration(StrictModel):
    api_host: AnyHttpUrl
    timeout_seconds: float = Field(gt=0, le=60)


class TimeConfiguration(StrictModel):
    pass


class WebSearchConfiguration(StrictModel):
    api_host: AnyHttpUrl
    timeout_seconds: float = Field(gt=0, le=60)
    max_results: int = Field(ge=1, le=20)


class CapabilityUpdate(StrictModel):
    enabled: bool
    configuration: dict[str, JsonValue]
    api_key: str | None = Field(default=None, min_length=1, max_length=2048)
    clear_api_key: bool = False

    @model_validator(mode="after")
    def validate_secret_action(self) -> "CapabilityUpdate":
        if self.api_key is not None and self.clear_api_key:
            raise ValueError("api_key and clear_api_key are mutually exclusive")
        return self
```

Define the boundary DTOs explicitly so plaintext and ciphertext cannot be confused:

```python
type CapabilityConfiguration = WeatherConfiguration | TimeConfiguration | WebSearchConfiguration


@dataclass(frozen=True)
class CapabilitySeed:
    key: CapabilityKey
    enabled: bool
    configuration: dict[str, JsonValue]
    api_key: str | None


@dataclass(frozen=True)
class StoredCapability:
    key: CapabilityKey
    enabled: bool
    configuration: dict[str, JsonValue]
    encrypted_api_key: str | None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class CapabilityState:
    key: CapabilityKey
    enabled: bool
    configuration: CapabilityConfiguration
    api_key: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class CapabilityView:
    key: CapabilityKey
    enabled: bool
    configuration: dict[str, JsonValue]
    api_key_masked: str | None
    can_reveal_api_key: bool
    updated_at: datetime | None
```

Only `CapabilityState` may hold decrypted API Keys, and it remains private to the in-process service. Normalize replacement keys with
`strip()` and reject a blank result before constructing a state.

- [ ] **Step 4: Implement repository transactions**

`CapabilityRepository` receives `async_sessionmaker[AsyncSession]` and implements:

```python
async def seed_missing(self, seeds: Sequence[StoredCapability]) -> None:
    async with self._sessions.begin() as session:
        existing = set(await session.scalars(select(Capability.key)))
        session.add_all(
            Capability(
                key=seed.key,
                enabled=seed.enabled,
                configuration=dict(seed.configuration),
                encrypted_api_key=seed.encrypted_api_key,
            )
            for seed in seeds
            if seed.key not in existing
        )

async def list(self) -> list[StoredCapability]:
    async with self._sessions() as session:
        rows = await session.scalars(select(Capability).order_by(Capability.key))
        return [
            StoredCapability(
                key=cast(CapabilityKey, row.key),
                enabled=row.enabled,
                configuration=dict(row.configuration),
                encrypted_api_key=row.encrypted_api_key,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

async def update(self, value: StoredCapability) -> StoredCapability | None:
    async with self._sessions.begin() as session:
        row = await session.scalar(
            select(Capability).where(Capability.key == value.key).with_for_update()
        )
        if row is None:
            return None
        row.enabled = value.enabled
        row.configuration = dict(value.configuration)
        row.encrypted_api_key = value.encrypted_api_key
        await session.flush()
        await session.refresh(row)
        return StoredCapability(
            key=cast(CapabilityKey, row.key),
            enabled=row.enabled,
            configuration=dict(row.configuration),
            encrypted_api_key=row.encrypted_api_key,
            updated_at=row.updated_at,
        )
```

No SQLAlchemy model may escape the repository.

- [ ] **Step 5: Implement validation, secret handling, and snapshot publication**

`CapabilityService` receives the repository, dedicated encryption secret, shared weather/search HTTP clients, and tool factories. Its core update flow must be:

```python
async def update(self, key: str, command: CapabilityUpdate) -> CapabilityView:
    async with self._update_lock:
        current = self._states.get(key)
        if current is None:
            raise CapabilityNotFoundError(key)
        configuration = parse_configuration(key, command.configuration)
        api_key = self._next_api_key(key, current.api_key, command)
        self._validate_enabled(key, command.enabled, api_key)
        candidate = replace(current, enabled=command.enabled, configuration=configuration, api_key=api_key)
        candidate_states = {**self._states, key: candidate}
        candidate_tools = self._build_tools(candidate_states)
        stored = await self._repository.update(self._to_stored(candidate))
        if stored is None:
            raise CapabilityNotFoundError(key)
        published = replace(candidate, updated_at=stored.updated_at)
        self._states = {**candidate_states, key: published}
        self._tools = candidate_tools
        return self._view(published)
```

`initialize()` encrypts seed secrets, calls `seed_missing`, decrypts stored rows, validates all fixed configurations, and assigns `_states` and `_tools` only after the complete candidate snapshot succeeds. If Fernet rejects one stored ciphertext, retain that row with no usable plaintext Key, omit its tool from the effective snapshot, and let reveal raise `CapabilitySecretUnavailableError`; this keeps the Admin repair path available without exposing the ciphertext. `snapshot()` returns the immutable tuple already stored in `_tools` without awaiting or touching the database.

Use the existing `encrypt_key`/`decrypt_key` primitives with the new dedicated secret. Mask configured values as `••••••••` plus the final four characters; never place plaintext in a view or exception.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all capability service tests pass with no warning output.

- [ ] **Step 7: Document and commit the module**

Write `capabilities/AGENTS.md` with module purpose, fixed schemas, repository boundary, initialization flow, snapshot semantics, secret rules, and extension instructions.

```bash
git add src/somai_chat/capabilities src/somai_chat/admin/capability_repository.py \
  tests/unit/test_capability_service.py
git commit -m "feat(capabilities): add persisted capability service"
```

### Task 3: Make provider adapters snapshot-configurable

**Files:**
- Modify: `src/somai_chat/weather/client.py`
- Modify: `src/somai_chat/web/search.py`
- Test: `tests/unit/test_weather.py`
- Test: `tests/unit/test_web_search.py`

- [ ] **Step 1: Write failing request-configuration tests**

Extend the existing mocked-transport tests to assert per-snapshot host and timeout:

```python
@pytest.mark.asyncio
async def test_weather_client_applies_its_configured_timeout() -> None:
    client = QWeatherClient(http_client, api_host="https://weather.example", api_key="key", timeout_seconds=7)

    await client.get_current_weather("武汉")

    assert all(request.extensions["timeout"]["read"] == 7 for request in captured_requests)


@pytest.mark.asyncio
async def test_tavily_client_uses_configured_host_and_timeout() -> None:
    client = TavilyClient(
        http_client,
        api_host="https://search.example",
        api_key="key",
        timeout_seconds=9,
        max_results=3,
    )

    await client.search("SOMAI")

    assert captured_request.url == "https://search.example/search"
    assert captured_request.extensions["timeout"]["read"] == 9
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_weather.py tests/unit/test_web_search.py -q
```

Expected: constructor errors because the adapters do not accept the new arguments.

- [ ] **Step 3: Apply timeout and host to every request**

Store `timeout_seconds` in `QWeatherClient` and pass `timeout=self._timeout_seconds` to its three HTTP calls. Change Tavily to store a stripped `api_host` and timeout, then call:

```python
response = await self._http_client.post(
    f"{self._api_host}/search",
    headers={"Authorization": f"Bearer {self._api_key}"},
    json=payload,
    timeout=self._timeout_seconds,
)
```

Update existing constructor calls in tests to supply explicit values only where needed; preserve current default timeouts in constructors for backward compatibility.

- [ ] **Step 4: Run focused tests and commit**

Run the Step 2 command. Expected: all tests pass.

```bash
git add src/somai_chat/weather/client.py src/somai_chat/web/search.py \
  tests/unit/test_weather.py tests/unit/test_web_search.py
git commit -m "refactor(tools): support runtime capability parameters"
```

### Task 4: Capture and execute one tool snapshot per conversation turn

**Files:**
- Modify: `src/somai_chat/application/conversation.py`
- Modify: `src/somai_chat/agent/graph.py`
- Test: `tests/unit/test_conversation.py`
- Test: `tests/unit/test_graph.py`

- [ ] **Step 1: Write failing snapshot tests**

Add a provider whose returned tuple can change and a model that records bound tool names. Cover both boundaries:

```python
@pytest.mark.asyncio
async def test_runtime_reads_tool_snapshot_once_per_turn() -> None:
    provider = ChangingToolProvider(first=(weather_tool,), second=(search_tool,))
    graph = SnapshotRecordingGraph()
    runtime = ConversationRuntime(graph, tool_provider=provider)

    await collect(runtime.stream("conv", "msg-1", "first"))
    await collect(runtime.stream("conv", "msg-2", "second"))

    assert graph.runtime_tool_names == [("get_weather",), ("web_search",)]
    assert provider.snapshot_calls == 2


@pytest.mark.asyncio
async def test_graph_uses_same_dynamic_tools_for_model_and_tool_node() -> None:
    model = DynamicToolCallingModel()
    graph = build_conversation_graph(
        model,
        tools=[camera_tool],
        dynamic_tools=True,
    )

    result = await graph.ainvoke(
        user_input("search"),
        config={"configurable": {"thread_id": "turn-a", "runtime_tools": (search_tool,)}},
    )

    assert model.bound_tool_names == {"camera_capture", "web_search"}
    assert any(isinstance(message, ToolMessage) for message in result["messages"])
```

Also retain an explicit regression test proving the existing static `tools=` behavior still works.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_conversation.py tests/unit/test_graph.py -q
```

Expected: constructor/signature failures for `tool_provider` and `dynamic_tools`.

- [ ] **Step 3: Add the transport-neutral snapshot provider**

In `conversation.py`, keep Application free of provider/httpx imports:

```python
class ToolSnapshotProvider(Protocol):
    def snapshot(self) -> Sequence[BaseTool]:
        raise NotImplementedError


class ConversationRuntime:
    def __init__(
        self,
        graph: ConversationGraph,
        model_unavailable_classifier: ModelUnavailableClassifier = _never_model_unavailable,
        image_analyzer: ImageAnalyzer | None = None,
        tool_provider: ToolSnapshotProvider | None = None,
    ) -> None:
        self._graph = graph
        self._model_unavailable_classifier = model_unavailable_classifier
        self._image_analyzer = image_analyzer
        self._tool_provider = tool_provider
        self._text_normalizer = TextNormalizer()

    def _graph_config(self, conversation_id: str) -> RunnableConfig:
        runtime_tools = tuple(self._tool_provider.snapshot()) if self._tool_provider is not None else ()
        return {
            "configurable": {
                "thread_id": conversation_id,
                "runtime_tools": runtime_tools,
            }
        }
```

Replace the existing inline `config` construction in `stream()` with `config = self._graph_config(conversation_id)` immediately
before opening the graph stream. `_graph_config()` calls `snapshot()` exactly once; keep all existing image, streaming, error, and
cancellation behavior unchanged.

- [ ] **Step 4: Bind and execute dynamic tools in the graph**

Add `dynamic_tools: bool = False` to `build_conversation_graph`. Resolve tools from the per-run configuration:

```python
def selected_tools(config: RunnableConfig) -> tuple[BaseTool, ...]:
    configurable = config.get("configurable", {})
    runtime_tools = configurable.get("runtime_tools", ()) if dynamic_tools else ()
    if not isinstance(runtime_tools, Sequence):
        raise ValueError("runtime_tools must be a sequence")
    if not all(isinstance(item, BaseTool) for item in runtime_tools):
        raise ValueError("runtime_tools must contain tools")
    return (*tools, *cast(Sequence[BaseTool], runtime_tools))


async def invoke_model(state: ConversationState, config: RunnableConfig) -> ConversationState:
    turn_tools = selected_tools(config)
    bound_model = model.bind_tools(list(turn_tools)) if turn_tools else model
    response = await bound_model.ainvoke(
        [SystemMessage(content=SOMAI_SYSTEM_PROMPT), *state["messages"]],
        config=config,
    )
    return {"messages": [response]}


async def invoke_tools(state: ConversationState, config: RunnableConfig) -> ConversationState:
    node = ToolNode(list(selected_tools(config)))
    return cast(ConversationState, await node.ainvoke(state, config=config))
```

Compile a tools node when static tools exist or `dynamic_tools=True`. Keep camera termination routing unchanged.

- [ ] **Step 5: Run focused tests and commit**

Run the Step 2 command. Expected: all selected tests pass, including cancellation and thread-isolation regressions.

```bash
git add src/somai_chat/application/conversation.py src/somai_chat/agent/graph.py \
  tests/unit/test_conversation.py tests/unit/test_graph.py
git commit -m "feat(agent): bind capabilities per conversation turn"
```

### Task 5: Expose safe Admin capability APIs

**Files:**
- Create: `src/somai_chat/api/capabilities.py`
- Modify: `src/somai_chat/main.py`
- Test: `tests/unit/test_capability_api.py`

- [ ] **Step 1: Write failing API tests**

Use direct async route calls with a service stub, matching the existing Admin API test style:

```python
@pytest.mark.asyncio
async def test_list_capabilities_requires_admin_and_never_returns_plaintext() -> None:
    request = admin_request(capability_service=service_stub(api_key="secret-value"))

    result = await list_capabilities(request)

    assert result[0]["api_key_masked"].endswith("alue")
    assert "secret-value" not in repr(result)


@pytest.mark.asyncio
async def test_update_capability_requires_csrf() -> None:
    request = admin_request(capability_service=service_stub(), csrf=False)

    with pytest.raises(HTTPException) as captured:
        await update_capability(request, "weather", valid_weather_payload())

    assert captured.value.status_code == 403


@pytest.mark.asyncio
async def test_reveal_returns_only_the_requested_secret() -> None:
    request = admin_request(capability_service=service_stub(api_key="weather-secret"))

    assert await reveal_capability_api_key(request, "weather") == {"api_key": "weather-secret"}
```

Add separate 404 tests for unknown capability and 422 tests for service validation errors.

- [ ] **Step 2: Run the API test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_capability_api.py -q
```

Expected: import failure because `api/capabilities.py` does not exist.

- [ ] **Step 3: Implement the router and safe mappings**

Create a router at `/api/v1/admin/capabilities` with:

```python
@router.get("")
async def list_capabilities(request: Request) -> list[dict[str, object]]:
    require_admin(request)
    return [view_to_response(view) for view in await _service(request).list_views()]


@router.put("/{capability}")
async def update_capability(
    request: Request,
    capability: str,
    payload: CapabilityUpdate,
) -> dict[str, object]:
    require_csrf(request)
    try:
        return view_to_response(await _service(request).update(capability, payload))
    except CapabilityNotFoundError:
        raise HTTPException(status_code=404, detail="Capability not found") from None
    except CapabilityValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@router.post("/{capability}/api-key/reveal")
async def reveal_capability_api_key(request: Request, capability: str) -> dict[str, str]:
    require_csrf(request)
    try:
        return {"api_key": await _service(request).reveal_api_key(capability)}
    except (CapabilityNotFoundError, CapabilitySecretUnavailableError):
        raise HTTPException(status_code=404, detail="Capability API Key is unavailable") from None
```

Do not put plaintext secrets into model `repr`, response models other than reveal, or exception messages. Include this router in `main.py` and initialize `application.state.capability_service = None` before lifespan.

- [ ] **Step 4: Run focused tests and commit**

Run the Step 2 command. Expected: all API tests pass.

```bash
git add src/somai_chat/api/capabilities.py src/somai_chat/main.py tests/unit/test_capability_api.py
git commit -m "feat(api): add capability management endpoints"
```

### Task 6: Compose, seed, and hot-load capabilities at application startup

**Files:**
- Modify: `src/somai_chat/main.py`
- Modify: `tests/unit/test_main.py`
- Modify: `tests/integration/test_app.py`

- [ ] **Step 1: Replace startup registration tests with failing capability-service tests**

Update `test_main.py` to verify production composition rather than startup-only settings:

```python
def test_application_seeds_and_injects_dynamic_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    service = CapabilityServiceStub(tool_names=("get_weather", "get_current_time"))

    monkeypatch.setattr(main_module, "CapabilityService", lambda *args, **kwargs: service)
    monkeypatch.setattr(main_module, "build_conversation_graph", capture_graph(captured))
    monkeypatch.setattr(main_module, "create_chat_model", lambda settings: object())
    monkeypatch.setattr(main_module.httpx, "AsyncClient", CloseTrackingAsyncClient)

    with TestClient(main_module.create_app(settings=configured_settings())) as client:
        assert client.app.state.capability_service is service

    assert service.initialized_seed_keys == {"weather", "time", "web_search"}
    assert captured["static_tool_names"] == {"camera_capture"}
    assert captured["dynamic_tools"] is True
    assert captured["runtime_tool_provider"] is service
```

Add a test that a configured Tavily key seeds search as enabled, an absent key seeds it disabled, and existing injected-runtime tests do not attempt a database query.

- [ ] **Step 2: Run focused startup tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_main.py tests/integration/test_app.py -q
```

Expected: failures because startup still constructs static weather/time/search tools.

- [ ] **Step 3: Compose the capability service**

In lifespan, create `CapabilityRepository`, two shared `httpx.AsyncClient` instances without provider-specific base URLs, and `CapabilityService`. Build seeds exactly once from `Settings`:

```python
seeds = (
    CapabilitySeed(
        key="weather",
        enabled=settings.qweather_api_host is not None and settings.qweather_api_key is not None,
        configuration={
            "api_host": str(settings.qweather_api_host) if settings.qweather_api_host else "https://devapi.qweather.com",
            "timeout_seconds": settings.weather_timeout_seconds,
        },
        api_key=settings.qweather_api_key.get_secret_value() if settings.qweather_api_key else None,
    ),
    CapabilitySeed(key="time", enabled=True, configuration={}, api_key=None),
    CapabilitySeed(
        key="web_search",
        enabled=settings.tavily_api_key is not None,
        configuration={
            "api_host": str(settings.tavily_api_host),
            "timeout_seconds": settings.tavily_timeout_seconds,
            "max_results": settings.tavily_max_results,
        },
        api_key=settings.tavily_api_key.get_secret_value() if settings.tavily_api_key else None,
    ),
)
await capability_service.initialize(seeds)
```

Build the graph with only the always-on camera tool and `dynamic_tools=True`; pass the service as `ConversationRuntime(tool_provider=capability_service)`. Remove the old mandatory QWeather startup error and static Tavily branch.

Keep test injection safe: when a complete `runtime` is passed to `create_app`, do not initialize production capability dependencies unless a capability service is also explicitly injected. Production `create_app()` still initializes all dependencies.

- [ ] **Step 4: Verify resource closure and GREEN**

Run the Step 2 command. Expected: all selected tests pass, shared HTTP clients close once, and readiness remains independent of provider network calls.

- [ ] **Step 5: Commit startup composition**

```bash
git add src/somai_chat/main.py tests/unit/test_main.py tests/integration/test_app.py
git commit -m "feat(core): hot-load persisted capabilities"
```

### Task 7: Add tested frontend draft and payload logic

**Files:**
- Create: `frontend/admin/src/capability-state.js`
- Create: `tests/js/admin_capability_state.mjs`
- Modify: `frontend/admin/package.json`

- [ ] **Step 1: Write the failing Node test**

Test real exported helpers without a DOM framework:

```javascript
import assert from "node:assert/strict";
import {
  createCapabilityDraft,
  createUpdatePayload,
  isCapabilityDraftDirty,
  validateCapabilityDraft,
} from "../../frontend/admin/src/capability-state.js";

const weather = {
  key: "weather",
  enabled: true,
  configuration: { api_host: "https://weather.example", timeout_seconds: 5 },
  api_key_masked: "••••••••-key",
  can_reveal_api_key: true,
};

assert.deepEqual(createUpdatePayload(createCapabilityDraft(weather)), {
  enabled: true,
  configuration: { api_host: "https://weather.example", timeout_seconds: 5 },
  clear_api_key: false,
});

const replacement = createCapabilityDraft(weather);
replacement.replacement_api_key = "replacement-key";
assert.equal(createUpdatePayload(replacement).api_key, "replacement-key");
assert.equal(isCapabilityDraftDirty(replacement), true);

const cleared = createCapabilityDraft(weather);
cleared.clear_api_key = true;
assert.equal(createUpdatePayload(cleared).clear_api_key, true);
assert.equal("api_key" in createUpdatePayload(cleared), false);

const incomplete = createCapabilityDraft({ ...weather, enabled: true, can_reveal_api_key: false });
assert.match(validateCapabilityDraft(incomplete), /API Key/);

const revealed = createCapabilityDraft(weather);
revealed.revealed_api_key = "view-only-secret";
assert.equal("api_key" in createUpdatePayload(revealed), false);
assert.equal(isCapabilityDraftDirty(revealed), false);
```

- [ ] **Step 2: Run the Node test and verify RED**

Run:

```bash
node tests/js/admin_capability_state.mjs
```

Expected: module-not-found failure for `capability-state.js`.

- [ ] **Step 3: Implement pure state helpers**

Export:

```javascript
export function createCapabilityDraft(view) {
  return {
    ...structuredClone(view),
    baseline: JSON.stringify({ enabled: view.enabled, configuration: view.configuration }),
    replacement_api_key: "",
    revealed_api_key: "",
    clear_api_key: false,
    saving: false,
    error: "",
  };
}

export function createUpdatePayload(draft) {
  const payload = {
    enabled: draft.enabled,
    configuration: structuredClone(draft.configuration),
    clear_api_key: draft.clear_api_key,
  };
  const replacement = draft.replacement_api_key.trim();
  if (replacement && !draft.clear_api_key) payload.api_key = replacement;
  return payload;
}
```

`validateCapabilityDraft()` must return an empty string for valid drafts; reject enabled weather/search without an existing or replacement Key, invalid HTTP(S) URLs, non-positive timeout, and search results outside 1–20. Reject simultaneous replacement and clear state. Time accepts only the switch.
`isCapabilityDraftDirty()` compares the current enabled/configuration JSON with `baseline` and also returns true for a replacement or
clear action; `revealed_api_key` is display-only and must never affect dirtiness or payloads.

Add `"test": "node ../../tests/js/admin_capability_state.mjs"` to the frontend package scripts.

- [ ] **Step 4: Run the test and commit**

Run:

```bash
node tests/js/admin_capability_state.mjs
```

Expected: process exits 0 and prints the test summary once.

```bash
git add frontend/admin/src/capability-state.js frontend/admin/package.json tests/js/admin_capability_state.mjs
git commit -m "test(admin): define capability card state"
```

### Task 8: Build the capability cards and keep Admin components focused

**Files:**
- Create: `frontend/admin/src/CapabilityManagement.vue`
- Create: `frontend/admin/src/ClientManagement.vue`
- Create: `frontend/admin/src/capability-cards.css`
- Modify: `frontend/admin/src/App.vue`
- Modify: `frontend/admin/src/main.js`
- Modify: `tests/integration/test_admin_web.py`

- [ ] **Step 1: Write failing source-level UI contract tests**

Add tests that inspect the responsible files rather than assuming all UI remains in `App.vue`:

```python
def test_admin_has_a_capability_management_view() -> None:
    source = admin_source("App.vue")
    capability = admin_source("CapabilityManagement.vue")

    assert 'index="capabilities"' in source
    assert "能力管理" in source
    assert "<CapabilityManagement" in source
    assert all(label in capability for label in ("查询天气", "查询时间", "联网搜索"))
    assert "/capabilities" in capability
    assert "保存配置" in capability


def test_admin_components_stay_within_repository_size_limit() -> None:
    source_directory = admin_source_directory()

    for component in source_directory.glob("*.vue"):
        assert len(component.read_text(encoding="utf-8").splitlines()) <= 500
```

Update existing client-card assertions to read `ClientManagement.vue` after extraction.

- [ ] **Step 2: Run the UI contract tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_admin_web.py -q
```

Expected: failures because the new components and navigation do not exist.

- [ ] **Step 3: Extract the existing client page without behavior changes**

Move the client-page section from `App.vue` into `ClientManagement.vue`. Give it explicit props for `clients`, `revealedKeys`, and the existing action callbacks, and emit only `create` for opening the existing dialog:

```vue
<script setup>
defineProps({
  clients: { type: Array, required: true },
  revealedKeys: { type: Object, required: true },
  loadClients: { type: Function, required: true },
  toggleClient: { type: Function, required: true },
  rotateClient: { type: Function, required: true },
  revealKey: { type: Function, required: true },
  copyKey: { type: Function, required: true },
  formatLastAuthentication: { type: Function, required: true },
});
defineEmits(["create"]);
</script>
```

Keep the existing client dialogs and state in `App.vue`; this is a focused view extraction, not a client-management rewrite.

- [ ] **Step 4: Implement `CapabilityManagement.vue`**

The component receives the existing authenticated `request` function as a required prop. On mount it loads `/capabilities`, maps views through `createCapabilityDraft`, and renders three cards in the service order.

Implement these exact operations:

```javascript
async function saveCapability(draft) {
  draft.error = validateCapabilityDraft(draft);
  if (draft.error) return;
  draft.saving = true;
  try {
    const saved = await props.request(`/capabilities/${draft.key}`, {
      method: "PUT",
      body: JSON.stringify(createUpdatePayload(draft)),
    });
    replaceDraft(saved);
    ElMessage.success("能力配置已保存，将从下一条消息开始生效");
  } catch (error) {
    draft.error = error.message;
  } finally {
    draft.saving = false;
  }
}

async function revealApiKey(draft) {
  const result = await props.request(`/capabilities/${draft.key}/api-key/reveal`, { method: "POST" });
  draft.revealed_api_key = result.api_key;
}
```

Add explicit `markKeyForClearing` and `cancelKeyReplacement` handlers. Never automatically copy or retain revealed plaintext after a successful save; replace the draft from the sanitized save response.

- [ ] **Step 5: Add layout and navigation**

Add the `MagicStick` icon and `capabilities` menu item between clients and chat. Use a title map instead of adding another nested ternary. Render:

```vue
<CapabilityManagement
  v-else-if="active === 'capabilities'"
  :request="request"
/>
```

Import `capability-cards.css` from `main.js`. Style `.capability-grid` as three equal cards, switch to two columns below 1200px and one below 760px. Include visible dirty/error/saving states, aligned card actions, and `overflow-wrap` for masked values. Do not add external fonts, scripts, or CDN assets.

- [ ] **Step 6: Run source tests, Node tests, and production build**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_admin_web.py -q
node tests/js/admin_capability_state.mjs
npm --prefix frontend/admin run build
```

Expected: all tests pass and Vite writes a successful build to `src/somai_chat/admin_web/dist`.

- [ ] **Step 7: Commit the Admin UI and generated bundle**

```bash
git add frontend/admin/src frontend/admin/package.json tests/integration/test_admin_web.py \
  src/somai_chat/admin_web/dist
git commit -m "feat(admin): add capability management cards"
```

### Task 9: Synchronize module documentation and verify the complete feature

**Files:**
- Modify: `README.md`
- Modify: `src/somai_chat/admin/AGENTS.md`
- Modify: `src/somai_chat/api/AGENTS.md`
- Modify: `src/somai_chat/application/AGENTS.md`
- Modify: `src/somai_chat/agent/AGENTS.md`
- Modify: `src/somai_chat/weather/AGENTS.md`
- Modify: `src/somai_chat/web/AGENTS.md`
- Modify: `frontend/admin/AGENTS.md`

- [ ] **Step 1: Update user and module documentation**

Document these exact externally relevant facts:

- Run Alembic through revision `0003` before using the page.
- Configure `SOMAI_CAPABILITY_SECRET_ENCRYPTION_SECRET` with a dedicated production secret.
- Environment weather/search settings seed only missing rows; the database owns subsequent values.
- Capability changes affect the next message and do not interrupt an active response.
- Weather, time, and web search are managed; camera and vision are not.
- API Key list values are masked and reveal requires Admin CSRF.
- The Agent graph consumes one immutable dynamic tool snapshot per turn.

Each `AGENTS.md` must describe only its own module responsibilities and data flow; do not duplicate the root coding rules.

- [ ] **Step 2: Run formatting and focused regression tests**

Run:

```bash
make format
node tests/js/admin_capability_state.mjs
npm --prefix frontend/admin run build
```

Expected: formatting succeeds, Node test exits 0, and Vite build succeeds without warnings that indicate missing imports.

- [ ] **Step 3: Run the full quality gate**

Run:

```bash
make check
```

Expected: Ruff, strict mypy, and the complete pytest suite all pass. If any failure appears, add the smallest regression test that reproduces it before changing production code.

- [ ] **Step 4: Inspect the final diff and file sizes**

Run:

```bash
git diff --check
git status --short
find src/somai_chat frontend/admin/src -type f \( -name '*.py' -o -name '*.vue' -o -name '*.js' \) \
  -exec awk 'FNR==1 { file=FILENAME } END { if (FNR > 500) print file ":" FNR }' {} \;
```

Expected: no whitespace errors, only feature-related changes, and no listed code file above 500 lines.

- [ ] **Step 5: Commit documentation and verification adjustments**

```bash
git add README.md src/somai_chat/*/AGENTS.md frontend/admin/AGENTS.md \
  frontend/admin/src src/somai_chat/admin_web/dist
git commit -m "docs: document dynamic capability management"
```

- [ ] **Step 6: Perform final verification after the last commit**

Run:

```bash
git status --short
make check
node tests/js/admin_capability_state.mjs
npm --prefix frontend/admin run build
```

Expected: clean worktree and every command exits successfully.
