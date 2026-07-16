.PHONY: install dev format lint typecheck test check

PYTHON := .venv/bin/python

install:
	uv venv --python 3.12
	uv pip install --python $(PYTHON) -e '.[dev]'

dev:
	uv run uvicorn somai_chat.main:app --reload --host 0.0.0.0 --port 8000 \
		--ws-max-size $${SOMAI_MAX_WEBSOCKET_MESSAGE_BYTES:-32768}

format:
	$(PYTHON) -m ruff format .

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest -q

check: lint typecheck test
