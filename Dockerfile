FROM python:3.12-slim AS builder

ARG UV_VERSION=0.11.13
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN python -m pip install "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app
RUN addgroup --system somai && adduser --system --ingroup somai somai
COPY --from=builder /app/.venv /app/.venv

USER somai
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; port = os.getenv('SOMAI_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health/live', timeout=2)"]
CMD ["python", "-m", "somai_chat.main"]
