# Split Database Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `SOMAI_DATABASE_URL` with five validated MySQL environment variables shared by application startup and Alembic.

**Architecture:** `Settings` owns the split fields and constructs a SQLAlchemy `URL` through `URL.create()`, so credentials are encoded safely without string concatenation. The composition root consumes the rendered URL, while Alembic loads the same Settings entry point and escapes percent signs only for ConfigParser interpolation.

**Tech Stack:** Python 3.12, Pydantic Settings, SQLAlchemy, Alembic, pytest, Ruff, mypy.

---

### Task 1: Define and validate split database settings

**Files:**
- Modify: `src/somai_chat/core/config.py`
- Modify: `tests/unit/test_config.py`
- Modify: `src/somai_chat/core/AGENTS.md`

- [ ] **Step 1: Write failing tests for defaults, custom fields, encoding, secrecy, and validation**

Replace URL-based tests with these behaviors:

```python
def test_settings_builds_database_url_from_split_fields() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="chat-secret",
        openai_model="chat-model",
        database_user="robot",
        database_password="p@ss:/#word",
        database_host="db.internal",
        database_port=3307,
        database_name="somai_chat",
    )

    url = make_url(settings.database_connection_url())

    assert url.drivername == "mysql+asyncmy"
    assert (url.username, url.password) == ("robot", "p@ss:/#word")
    assert (url.host, url.port, url.database) == ("db.internal", 3307, "somai_chat")


def test_database_settings_have_documented_defaults() -> None:
    settings = Settings(_env_file=None, openai_api_key="secret", openai_model="model")

    assert settings.database_user == "somai"
    assert settings.database_password.get_secret_value() == "change-me"
    assert settings.database_host == "127.0.0.1"
    assert settings.database_port == 3306
    assert settings.database_name == "somai"


@pytest.mark.parametrize("field", ["database_user", "database_password", "database_host", "database_name"])
def test_settings_rejects_blank_database_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_api_key="secret", openai_model="model", **{field: "   "})


def test_database_password_is_hidden_from_repr() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="secret",
        openai_model="model",
        database_password="database-secret",
    )

    assert "database-secret" not in repr(settings)
```

Update production placeholder tests to set `database_password` instead of `database_url`, and add port boundary cases `0` and `65536`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_config.py -q
```

Expected: failures because the split fields and `database_connection_url()` do not exist.

- [ ] **Step 3: Implement split fields and safe URL construction**

In `Settings`, replace `database_url` with:

```python
database_user: str = Field(default="somai", min_length=1)
database_password: SecretStr = SecretStr("change-me")
database_host: str = Field(default="127.0.0.1", min_length=1)
database_port: int = Field(default=3306, ge=1, le=65535)
database_name: str = Field(default="somai", min_length=1)

def database_connection_url(self) -> str:
    return URL.create(
        "mysql+asyncmy",
        username=self.database_user,
        password=self.database_password.get_secret_value(),
        host=self.database_host,
        port=self.database_port,
        database=self.database_name,
    ).render_as_string(hide_password=False)
```

Add a pre-validator that strips and rejects blank string fields, validate `database_password` as a nonblank secret, and change the production placeholder check to inspect only `database_password.get_secret_value()`. Delete URL parsing and the `database_url` validator.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all config tests pass.

- [ ] **Step 5: Update Core module documentation and commit**

Document the five fields, `SecretStr` password, `URL.create()` boundary, and production placeholder rule.

```bash
git add src/somai_chat/core/config.py src/somai_chat/core/AGENTS.md tests/unit/test_config.py
git commit -m "refactor(core): split database connection settings"
```

### Task 2: Share the generated URL with application startup and Alembic

**Files:**
- Modify: `src/somai_chat/main.py`
- Modify: `alembic/env.py`
- Modify: `tests/unit/test_main.py`
- Create: `tests/unit/test_alembic_config.py`
- Modify: `src/somai_chat/AGENTS.md`
- Modify: `src/somai_chat/admin/AGENTS.md`

- [ ] **Step 1: Write failing composition and Alembic tests**

Update the dotenv fixture in `test_main.py` to contain all five `SOMAI_DATABASE_*` fields and assert the old URL variable is absent.
Add a focused composition test:

```python
def test_application_uses_generated_database_connection_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class Closeable:
        async def dispose(self) -> None:
            return None

    def create_sessions(url: str) -> tuple[Closeable, object]:
        captured["url"] = url
        return Closeable(), object()

    settings = Settings(
        _env_file=None,
        openai_api_key="secret",
        openai_model="model",
        database_user="robot",
        database_password="p@ssword",
        database_host="db",
        database_name="chat",
    )

    monkeypatch.setattr(main_module, "create_session_factory", create_sessions)
    # Exercise lifespan with injected runtime so no model or provider network call occurs.
    with TestClient(main_module.create_app(settings=settings, runtime=cast(ConversationRuntime, object()))):
        pass

    assert make_url(captured["url"]).password == "p@ssword"
```

In `test_alembic_config.py`, import the Alembic environment with split environment variables and assert its configured
`sqlalchemy.url` decodes to the expected username, password, host, port, and database. Include a password containing `%` and `@` to
prove ConfigParser interpolation is handled.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_main.py tests/unit/test_alembic_config.py -q
```

Expected: failures because `main.py` and Alembic still read `database_url`/`SOMAI_DATABASE_URL`.

- [ ] **Step 3: Update application and Alembic consumers**

Change the composition root to:

```python
database_engine, sessions = create_session_factory(resolved_settings.database_connection_url())
```

In `alembic/env.py`, remove direct `os.environ` access and configure the shared Settings URL before migrations:

```python
from somai_chat.core.config import get_settings

database_url = get_settings().database_connection_url()
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
```

The percent replacement is only for Alembic's ConfigParser layer; `get_main_option()` returns the original SQLAlchemy URL. Do not log
the rendered URL.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Synchronize module documentation and commit**

Document that the composition root and Alembic share `Settings.database_connection_url()` and that no module reads a complete database
URL environment variable.

```bash
git add src/somai_chat/main.py alembic/env.py tests/unit/test_main.py tests/unit/test_alembic_config.py \
  src/somai_chat/AGENTS.md src/somai_chat/admin/AGENTS.md
git commit -m "refactor(database): share split settings with alembic"
```

### Task 3: Migrate examples and verify the repository

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing repository-contract assertions**

Add assertions that `.env.example` contains all five new names and excludes `SOMAI_DATABASE_URL`. Search relevant source, Alembic,
tests, README, and examples for the removed name; historical design/plan documents are exempt because they describe earlier behavior.

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/unit/test_config.py -q
```

Expected: failure because `.env.example` and README still use the old URL.

- [ ] **Step 3: Update examples and migration instructions**

Replace the old example with:

```dotenv
SOMAI_DATABASE_USER=somai
SOMAI_DATABASE_PASSWORD=replace-with-password
SOMAI_DATABASE_HOST=127.0.0.1
SOMAI_DATABASE_PORT=3306
SOMAI_DATABASE_NAME=somai
```

Update README's Alembic command to use `.env` directly, explain that `SOMAI_HOST`/`SOMAI_PORT` belong to Uvicorn, and add a short
upgrade note mapping each URL component to its new field. Do not include a real credential.

- [ ] **Step 4: Run all verification commands**

Run:

```bash
make check
node tests/js/admin_capability_state.mjs
npm --prefix frontend/admin run build
git diff --check
```

Expected: Ruff, strict mypy, all pytest tests, the Admin Node harness, and the production frontend build pass. Only the existing
Starlette/httpx deprecation and Vite chunk-size warnings may remain.

- [ ] **Step 5: Commit documentation and examples**

```bash
git add .env.example README.md tests/unit/test_config.py
git commit -m "docs: document split database settings"
```

- [ ] **Step 6: Verify the committed result**

Run:

```bash
git status --short
make check
```

Expected: clean worktree and all quality checks pass.
