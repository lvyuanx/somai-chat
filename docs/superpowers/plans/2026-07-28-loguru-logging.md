# Loguru Logging Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current application logging backend with Loguru while preserving safe correlation fields, dependency routing, and operational compatibility.

**Architecture:** `somai_chat.core.logging` owns Loguru sinks, standard-library interception, routing filters, and the legacy `JsonFormatter` compatibility surface. Settings supplies the log directory and level; the composition root configures logging once per lifespan, while application modules use a bound `source="project"` logger. Named dependency loggers are intercepted without changing root/Uvicorn handlers.

**Tech Stack:** Python 3.12, Loguru, standard-library `logging`, Pydantic Settings, pytest, Ruff, mypy.

---

### Task 1: Add Loguru dependency and logging configuration setting

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/somai_chat/core/config.py`
- Modify: `.env.example`
- Test: `tests/unit/test_config.py` (extend existing settings coverage if present)

- [ ] **Step 1: Write the failing test**

Add a settings test asserting `Settings(...).log_dir` accepts a supplied `Path` and defaults to a `logs` directory below the current working directory.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/unit/test_config.py -q`
Expected: FAIL because `Settings` has no `log_dir` field.

- [ ] **Step 3: Write the minimal implementation**

Add `loguru>=0.7,<1` to runtime dependencies, add `log_dir: Path = Field(default_factory=lambda: Path.cwd() / "logs")`, document `SOMAI_LOG_DIR` in `.env.example`, and regenerate the lock file with `uv lock`.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `pytest tests/unit/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/somai_chat/core/config.py .env.example tests/unit/test_config.py
git commit -m "feat: add loguru dependency and log directory setting"
```

### Task 2: Replace the logging backend with Loguru

**Files:**
- Modify: `src/somai_chat/core/logging.py`
- Test: `tests/unit/test_logging.py`

- [ ] **Step 1: Write failing routing and interception tests**

Cover these behaviors with a temporary directory and `io.StringIO` stream:

```python
def test_loguru_routes_project_records_to_project_outputs(tmp_path: Path) -> None:
    configure_logging("INFO", log_dir=tmp_path, stream=stream)
    get_logger().info("fixed event")
    assert "fixed event" in stream.getvalue()
    assert "fixed event" in (tmp_path / f"{date.today():%Y-%m-%d}-project.log").read_text()

def test_loguru_routes_errors_to_error_file(tmp_path: Path) -> None:
    configure_logging("INFO", log_dir=tmp_path, stream=io.StringIO())
    get_logger().error("failed")
    assert "failed" in (tmp_path / f"{date.today():%Y-%m-%d}-error.log").read_text()

def test_standard_logging_is_intercepted_without_replacing_root(tmp_path: Path) -> None:
    root_handler = logging.StreamHandler(io.StringIO())
    root = logging.getLogger()
    original = root.handlers[:]
    root.handlers = [root_handler]
    try:
        configure_logging("INFO", log_dir=tmp_path, stream=io.StringIO())
        logging.getLogger("somai_chat.test").info("fixed event")
        assert "fixed event" in (tmp_path / f"{date.today():%Y-%m-%d}-project.log").read_text()
        assert root.handlers == [root_handler]
    finally:
        root.handlers = original
```

Retain the existing `JsonFormatter` test to prove sensitive `extra` values remain excluded.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/unit/test_logging.py -q`
Expected: FAIL because the current implementation has no Loguru sinks, `get_logger`, or `log_dir` parameter.

- [ ] **Step 3: Implement the minimal Loguru configuration**

Implement `CONSOLE_LEVEL_COLORS`, `_InterceptHandler`, `configure_logging`, `setup_logging` alias, `get_logger`, and `JsonFormatter`. Configure dated all/project/error files plus the project-only console sink; bind correlation fields when intercepting application records; configure only `somai_chat` and the known dependency logger names, leaving root/Uvicorn handlers unchanged. Make the idempotence key include resolved directory, normalized level, and stream identity.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/unit/test_logging.py -q`
Expected: PASS with no duplicate lines on repeated configuration.

- [ ] **Step 5: Commit**

```bash
git add src/somai_chat/core/logging.py tests/unit/test_logging.py
git commit -m "feat: configure application logging with loguru"
```

### Task 3: Migrate application call sites and composition-root configuration

**Files:**
- Modify: `src/somai_chat/main.py`
- Modify: `src/somai_chat/api/websocket.py`
- Test: `tests/integration/test_websocket_logging.py`
- Test: `tests/integration/test_app.py`

- [ ] **Step 1: Write the failing integration assertions**

Update log capture to inspect the Loguru project stream/file output and assert lifecycle/error messages retain the same correlation IDs and omit user/provider secrets. Add an assertion that `create_app` passes `settings.log_dir` to logging setup.

- [ ] **Step 2: Run the focused integration tests to verify they fail**

Run: `pytest tests/integration/test_websocket_logging.py tests/integration/test_app.py -q`
Expected: FAIL because call sites still use stdlib logger and the lifespan does not pass a log directory.

- [ ] **Step 3: Migrate call sites**

Replace module-level `logging.getLogger(__name__)` in `main.py` and `api/websocket.py` with `get_logger()`, pass `resolved_settings.log_dir` to `configure_logging`, and preserve the existing fixed messages and correlation extras through Loguru `bind`/`extra` data.

- [ ] **Step 4: Run focused integration tests**

Run: `pytest tests/integration/test_websocket_logging.py tests/integration/test_app.py -q`
Expected: PASS, including safe logging assertions.

- [ ] **Step 5: Commit**

```bash
git add src/somai_chat/main.py src/somai_chat/api/websocket.py tests/integration/test_websocket_logging.py tests/integration/test_app.py
git commit -m "refactor: route application logs through loguru"
```

### Task 4: Synchronize module documentation and run the full verification suite

**Files:**
- Modify: `src/somai_chat/core/AGENTS.md`
- Modify: `src/somai_chat/AGENTS.md`
- Modify: `PROJECT_AGENTS.md` only if the effective logging contract changes

- [ ] **Step 1: Update module documentation**

Document Loguru sinks, `get_logger`, the log directory setting, interception scope, and the fact that root/Uvicorn handlers remain untouched.

- [ ] **Step 2: Run formatting, lint, type checks, and tests**

Run: `make format && make lint && make typecheck && make test`
Expected: all commands exit 0.

- [ ] **Step 3: Review the final diff and commit documentation**

Run: `git diff --check && git status --short`, then commit the documentation and any test-only cleanup:

```bash
git add src/somai_chat/core/AGENTS.md src/somai_chat/AGENTS.md PROJECT_AGENTS.md
git commit -m "docs: update logging module guidance"
```
