# Docker Compose and Nginx Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a one-command, HTTP-only Docker Compose deployment with Nginx as the sole public endpoint.

**Architecture:** Compose builds one single-process SOMAI application container and starts a second Nginx reverse-proxy container. Only Nginx publishes port 80; Nginx waits for the application health check and forwards normal HTTP and upgraded WebSocket requests through the internal Compose network.

**Tech Stack:** Docker Compose v2, existing Python 3.12 production Docker image, official Nginx Alpine image.

---

## File Structure

- Create: `compose.yaml` - production app and Nginx service topology.
- Create: `nginx/default.conf` - HTTP and WebSocket proxy configuration.
- Create: `.env.production.example` - production placeholders and origin guidance.
- Modify: `README.md` - clone, configure, start, verify, update, and stop instructions.

### Task 1: Define the Compose topology

**Files:**
- Create: `compose.yaml`

- [ ] **Step 1: Write the Compose validation command**

```bash
docker compose --env-file .env.production.example config --quiet
```

Expected: FAIL because `compose.yaml` does not exist.

- [ ] **Step 2: Create the two-service Compose file**

```yaml
services:
  app:
    build:
      context: .
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"]
      interval: 30s
      timeout: 3s
      start_period: 10s
      retries: 3

  nginx:
    image: nginx:1.27-alpine
    depends_on:
      app:
        condition: service_healthy
    ports:
      - "80:80"
    restart: unless-stopped
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
```

The `app` service must not have a `ports` entry. The application remains one Compose service and
does not declare replicas.

- [ ] **Step 3: Verify the Compose file parses**

Run: `docker compose --env-file .env.production.example config --quiet`

Expected: exit code 0.

### Task 2: Add WebSocket-capable Nginx proxying

**Files:**
- Create: `nginx/default.conf`

- [ ] **Step 1: Write the Nginx syntax validation command**

```bash
docker run --rm \
  -v "$PWD/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.27-alpine nginx -t
```

Expected: FAIL because the configuration file does not exist.

- [ ] **Step 2: Create the Nginx configuration**

```nginx
server {
    listen 80;
    server_name _;

    location /api/v1/chat/ws/ {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://app:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **Step 3: Verify Nginx syntax**

Run: `docker run --rm -v "$PWD/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t`

Expected: output includes `syntax is ok` and `test is successful`.

### Task 3: Document production setup

**Files:**
- Create: `.env.production.example`
- Modify: `README.md`

- [ ] **Step 1: Add production placeholders**

```env
SOMAI_ENVIRONMENT=production
SOMAI_HOST=0.0.0.0
SOMAI_PORT=8000
SOMAI_OPENAI_BASE_URL=https://api.openai.com/v1
SOMAI_OPENAI_API_KEY=replace-with-your-api-key
SOMAI_OPENAI_MODEL=replace-with-compatible-model
SOMAI_QWEATHER_API_HOST=https://replace-with-your-api-host.qweatherapi.com
SOMAI_QWEATHER_API_KEY=replace-with-your-api-key
SOMAI_ALLOWED_ORIGINS=["http://replace-with-server-ip-or-domain"]
```

- [ ] **Step 2: Add README deployment instructions**

Document these exact commands:

```bash
cp .env.production.example .env
chmod 600 .env
docker compose up -d --build
curl http://127.0.0.1/health/ready
docker compose logs -f
docker compose down
```

State that port 80 must be permitted by the server firewall, only Nginx is public, the origin must
match the browser address exactly, and the application cannot scale to multiple replicas yet.

- [ ] **Step 3: Verify tracked files contain no credentials**

Run: `git diff --check && git diff -- .env.production.example README.md`

Expected: no whitespace errors and only placeholder values.

### Task 4: Run final validation

**Files:**
- Modify: `docs/superpowers/plans/2026-07-17-compose-nginx-deployment.md` - mark verified steps complete.

- [ ] **Step 1: Run all deployment configuration checks**

Run: `docker compose --env-file .env.production.example config --quiet && docker run --rm -v "$PWD/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro" nginx:1.27-alpine nginx -t`

Expected: both commands exit successfully.

- [ ] **Step 2: Run project checks**

Run: `make check`

Expected: Ruff, mypy, and pytest exit successfully.

- [ ] **Step 3: Commit the deployment files and completed checklist**

```bash
git add compose.yaml nginx/default.conf .env.production.example README.md \
  docs/superpowers/plans/2026-07-17-compose-nginx-deployment.md
git commit -m "feat: add Compose Nginx deployment"
```
