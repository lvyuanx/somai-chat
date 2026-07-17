# Docker Compose and Nginx Deployment Design

## Goal

Provide a one-command, HTTP-only server deployment for SOMAI Chat after the operator clones the
repository and configures `.env`.

## Architecture

Docker Compose runs two services on a private Compose network:

- `app` builds the existing production Docker image and listens only on its internal port 8000. It
  is not published to the host.
- `nginx` is the sole public entry point and publishes host port 80. It proxies normal HTTP traffic
  and upgrades the conversation WebSocket route.

Both services restart unless explicitly stopped. Nginx waits for the app health check before
starting. The application remains a single replica because its session state and conversation locks
are process-local.

## Configuration

Compose consumes the operator-managed `.env` file. It must set `SOMAI_ENVIRONMENT=production`,
model and QWeather credentials, and `SOMAI_ALLOWED_ORIGINS` to the actual HTTP origin, such as the
server IP or future domain. A committed production example documents these values using placeholders
only; it contains no credentials.

## Nginx Behavior

Nginx proxies `/` and static assets as ordinary HTTP requests. It proxies `/api/v1/chat/ws/` with
HTTP/1.1, forwards `Upgrade` and `Connection` headers, and preserves the original host and client
address headers. No TLS or certificate configuration is included in this initial deployment.

## Operator Workflow

After configuring `.env`, the operator runs `docker compose up -d --build`. Health can be checked
at `/health/live` and `/health/ready`; `docker compose logs -f` provides diagnostics. The deployment
guide explains shutdown and rebuild commands.

## Scope

This deployment does not add TLS, certificate automation, multiple application replicas,
authentication, persistent sessions, or secrets-management infrastructure.
