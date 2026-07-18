# Robot Admin Client Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Build a dark administration console for robot clients, MySQL-backed client Keys, and authenticated WebSocket access while retaining Chat as an administrator workspace.

**Architecture:** Add an \`admin\` boundary for SQLAlchemy models, repositories, credentials, sessions, and HTTP routes. The WebSocket transport accepts either the signed administrator session or a validated robot Bearer Key. Static admin assets use the existing no-build browser pattern, while Alembic owns every database schema change.

**Tech Stack:** FastAPI, Starlette session middleware, SQLAlchemy 2 async ORM, asyncmy, Alembic, MySQL, Pydantic Settings, native HTML/CSS/ES modules, pytest, Ruff, mypy.

---

### Task 1: Add MySQL and administrator configuration

**Files:**
- Modify: \`pyproject.toml\`, \`src/somai_chat/core/config.py\`, \`.env.example\`
- Test: \`tests/unit/test_config.py\`

- [ ] **Step 1: Write failing configuration tests.**

~~~python
def test_settings_accepts_mysql_and_admin_configuration() -> None:
    settings = Settings(
        openai_api_key="secret", openai_model="model",
        database_url="mysql+asyncmy://somai:pass@db:3306/somai",
        admin_session_secret="session-secret", client_key_pepper="pepper",
    )
    assert settings.admin_username == "admin"
    assert settings.admin_password.get_secret_value() == "123456"

def test_production_rejects_default_admin_password() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            openai_api_key="secret",
            openai_model="model",
            database_url="mysql+asyncmy://somai:pass@db:3306/somai",
            admin_session_secret="session-secret",
            client_key_pepper="pepper",
        )
~~~

- [ ] **Step 2: Run \`.venv/bin/python -m pytest tests/unit/test_config.py -k 'mysql or admin' -v\` and confirm failure because these fields do not exist.**
- [ ] **Step 3: Add bounded \`SQLAlchemy\`, \`asyncmy\`, and \`alembic\` dependencies. Add \`database_url\`, \`admin_username=admin\`, \`admin_password=123456\`, \`admin_session_secret\`, and \`client_key_pepper\` to \`Settings\`; use \`SecretStr\` for all secrets and reject default/placeholder administrative secrets in production. Add matching \`SOMAI_\` settings to \`.env.example\`.**
- [ ] **Step 4: Re-run the focused tests; confirm PASS.**
- [ ] **Step 5: Commit only these configuration and lock-file changes as \`feat: configure admin database security\`.**

### Task 2: Define the versioned MySQL schema

**Files:**
- Create: \`src/somai_chat/admin/models.py\`, \`alembic.ini\`, \`alembic/env.py\`
- Create: \`alembic/versions/0001_create_client_credentials.py\`
- Test: \`tests/unit/test_admin_models.py\`

- [ ] **Step 1: Write a failing metadata test.**

~~~python
def test_client_key_schema_keeps_key_material_separate() -> None:
    assert set(Base.metadata.tables) == {"clients", "client_access_keys"}
    keys = Base.metadata.tables["client_access_keys"].c
    assert {"key_id", "secret_digest", "expires_at", "revoked_at"} <= set(keys)
    assert "raw_key" not in keys
~~~

- [ ] **Step 2: Run \`.venv/bin/python -m pytest tests/unit/test_admin_models.py -v\`; confirm it fails because admin models do not exist.**
- [ ] **Step 3: Implement typed declarative \`Client\` and \`ClientAccessKey\` models. The client has UUID ID, unique name, optional description, enabled flag, timestamps, and last-authenticated timestamp. The Key has UUID ID, unique public Key ID, HMAC digest, nullable expiry, last-use time, revoked time, and a cascading client foreign key. Index public Key ID and active-Key lookup fields.**
- [ ] **Step 4: Configure Alembic async metadata discovery and author the initial revision with equivalent MySQL tables, foreign key, uniqueness, and indexes. Run the metadata test and a disposable-MySQL \`alembic upgrade head\` test; confirm PASS.**
- [ ] **Step 5: Commit models, migration setup, revision, and tests as \`feat: add client credential schema\`.**

### Task 3: Implement Key generation, verification, and client lifecycle

**Files:**
- Create: \`src/somai_chat/admin/credentials.py\`, \`src/somai_chat/admin/repository.py\`, \`src/somai_chat/admin/service.py\`, \`src/somai_chat/admin/__init__.py\`, \`src/somai_chat/admin/AGENTS.md\`
- Test: \`tests/unit/test_client_credentials.py\`, \`tests/integration/test_client_repository.py\`

- [ ] **Step 1: Write failing Key behavior tests.**

~~~python
def test_generated_key_is_verifiable_without_storing_secret() -> None:
    key, record = create_client_key(pepper="test-pepper")
    assert key.startswith(f"somai_sk_{record.key_id}_")
    assert record.secret_digest != key
    assert verify_client_key(key, record, pepper="test-pepper")

async def test_rotating_key_revokes_previous_key_immediately(repository) -> None:
    client, previous_key = await repository.create_client(name="robot-a", expires_at=None)
    replacement = await repository.rotate_key(client.id, expires_at=None)
    assert await repository.authenticate(previous_key) is None
    assert await repository.authenticate(replacement) is not None
~~~

- [ ] **Step 2: Run \`.venv/bin/python -m pytest tests/unit/test_client_credentials.py tests/integration/test_client_repository.py -v\`; confirm failure because Key services are absent.**
- [ ] **Step 3: Generate \`somai_sk_<key-id>_<random-secret>\` using \`secrets.token_urlsafe(32)\`; use HMAC-SHA256 with the configured Pepper and \`hmac.compare_digest\`. Parse the Key safely, look up its public ID, then verify its digest.**
- [ ] **Step 4: Implement transactional create, list, get, update, enable/disable, delete, rotate, authenticate, and last-use methods. Authentication returns no reason for malformed, unknown, expired, revoked, disabled, or deleted Key values. Rotation creates a new Key record and marks every previously active Key for that client revoked in the same transaction.**
- [ ] **Step 5: Add and run expiry, immediate-revocation, disabled-client, deleted-client, and last-use tests; confirm PASS.**
- [ ] **Step 6: Commit admin services, docs, and tests as \`feat: manage robot client keys\`.**

### Task 4: Add signed administrator sessions and management API

**Files:**
- Create: \`src/somai_chat/admin/auth.py\`, \`src/somai_chat/api/admin.py\`
- Modify: \`src/somai_chat/main.py\`, \`src/somai_chat/core/errors.py\`
- Test: \`tests/integration/test_admin_api.py\`

- [ ] **Step 1: Write failing HTTP behavior tests.**

~~~python
def test_clients_api_requires_admin_session(client: TestClient) -> None:
    assert client.get("/api/v1/admin/clients").status_code == 401

def test_create_client_returns_plain_key_once(client: TestClient) -> None:
    csrf = login_and_get_csrf(client)
    response = client.post(
        "/api/v1/admin/clients",
        headers={"X-CSRF-Token": csrf},
        json={"name": "robot-a", "expires_at": None},
    )
    assert response.status_code == 201
    assert response.json()["key"].startswith("somai_sk_")
~~~

- [ ] **Step 2: Run \`.venv/bin/python -m pytest tests/integration/test_admin_api.py -v\`; confirm routes are absent.**
- [ ] **Step 3: Add \`SessionMiddleware\` with production-only Secure cookies. Implement constant-time configured-password verification, signed administrator session state, readable CSRF token delivery, CSRF-header validation for every state-changing request, and an in-process per-source login failure window.**
- [ ] **Step 4: Implement \`POST/DELETE/GET /api/v1/admin/session\`, \`GET/POST /clients\`, \`GET/PATCH/DELETE /clients/{client_id}\`, \`POST /clients/{client_id}/enabled\`, and \`POST /clients/{client_id}/keys/rotate\`. Validate pagination, names, descriptions, UTC future expiry, and long-lived \`null\` expiry. Use stable 401, 403, 404, 409, and 422 response bodies.**
- [ ] **Step 5: Re-run API tests for success, CSRF rejection, login limit, expiry validation, one-time Key output, and immediate rotation; confirm PASS. Commit as \`feat: add admin client management API\`.**

### Task 5: Authenticate WebSocket connections

**Files:**
- Modify: \`src/somai_chat/api/websocket.py\`, \`src/somai_chat/api/AGENTS.md\`
- Test: \`tests/integration/test_app.py\`, \`tests/integration/test_uvicorn_websocket.py\`

- [ ] **Step 1: Write failing WebSocket tests.**

~~~python
def test_robot_key_allows_websocket(client: TestClient, active_key: str) -> None:
    with client.websocket_connect(
        "/api/v1/chat/ws/conv_robot",
        headers={"authorization": f"Bearer {active_key}"},
    ) as socket:
        assert socket.receive_json()["type"] == "conversation.ready"

def test_missing_robot_credentials_close_with_policy_code(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/chat/ws/conv_robot") as socket:
        with pytest.raises(WebSocketDisconnect) as captured:
            socket.receive_json()
    assert captured.value.code == 1008
~~~

- [ ] **Step 2: Run the focused tests and confirm failure because unauthenticated device connections are accepted.**
- [ ] **Step 3: Before \`conversation.ready\`, accept authenticated administrator Cookie sessions or delegate Bearer header verification to the admin service. Never log the header or Key, preserve all existing Origin/ready/message semantics, and close every authentication failure with 1008 without a close reason. On successful robot authentication, update client and Key last-use data.**
- [ ] **Step 4: Run in-process and live-Uvicorn tests for valid administrator Cookie, valid Key, missing Key, malformed Key, expired Key, revoked Key, disabled client, and unconfigured Origin. Confirm PASS.**
- [ ] **Step 5: Commit as \`feat: authenticate robot websocket clients\`.**

### Task 6: Build the dark administration console and Chat workspace

**Files:**
- Create: \`src/somai_chat/admin_web/index.html\`, \`src/somai_chat/admin_web/admin.css\`, \`src/somai_chat/admin_web/admin.js\`, \`src/somai_chat/admin_web/AGENTS.md\`
- Modify: \`src/somai_chat/main.py\`, \`src/somai_chat/web/index.html\`, \`src/somai_chat/web/app.css\`, \`src/somai_chat/web/app.js\`
- Test: \`tests/integration/test_admin_web.py\`, \`tests/js/admin_console.mjs\`

- [ ] **Step 1: Write failing route tests.**

~~~python
def test_root_redirects_to_admin_login(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/admin/login"

def test_admin_shell_requires_session(client: TestClient) -> None:
    assert client.get("/admin").status_code == 401
~~~

- [ ] **Step 2: Run \`.venv/bin/python -m pytest tests/integration/test_admin_web.py -v\`; confirm root still serves the old debug console.**
- [ ] **Step 3: Implement login and responsive shell with the approved graphite background, \`#5796FF\` active state, and \`#FF7866\` destructive state. Render only Overview, Clients, and Chat navigation. Implement client list, status/expiry/last-use fields, optional-expiry creation, one-time Key modal, immediate-rotation confirmation, enable/disable/delete operations, empty/loading/error states, and an authenticated Chat workspace that reuses the existing protocol state machine.**
- [ ] **Step 4: Add DOM tests that assert Key dismissal removes raw Key text and that every mutation sends the CSRF header. Run web route, DOM, and existing Chat state tests; confirm PASS.**
- [ ] **Step 5: Commit the console as \`feat: add robot administration console\`.**

### Task 7: Document deployment, package assets, and verify release output

**Files:**
- Modify: \`README.md\`, \`src/somai_chat/core/AGENTS.md\`, \`src/somai_chat/web/AGENTS.md\`, \`tests/integration/test_distribution.py\`, \`Dockerfile\`
- Test: \`tests/integration/test_distribution.py\`

- [ ] **Step 1: Write a failing wheel-content test for \`somai_chat/admin_web/index.html\`, \`admin.css\`, and \`admin.js\`. Run \`.venv/bin/python -m pytest tests/integration/test_distribution.py -k admin -v\` and confirm failure before package-data support is complete.**
- [ ] **Step 2: Update package configuration and distribution tests so wheel and sdist contain old Chat assets and all new admin assets.**
- [ ] **Step 3: Update README and module AGENTS docs with configuration, Alembic deployment command, production credential requirements, one-time Key behavior, immediate rotation, Bearer WebSocket handshake, admin entry route, and Chat workspace behavior. Document migrations as an explicit deployment step rather than baking credentials into the image.**
- [ ] **Step 4: Run \`make check && node tests/js/admin_console.mjs && node tests/js/web_console_state.mjs && node tests/js/console_view.mjs && uv build\`. Confirm every check passes and artifacts contain both static applications.**
- [ ] **Step 5: Commit documentation and distribution work as \`docs: document robot admin deployment\`.**
