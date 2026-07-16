.PHONY: install dev format lint typecheck test check

PYTHON := .venv/bin/python

install:
	uv venv --python 3.12
	uv pip install --python $(PYTHON) -e '.[dev]'

dev:
	@if [ ! -f src/somai_chat/main.py ]; then \
		echo "API entry point is not implemented yet; complete Task 5"; \
		exit 1; \
	fi
	uv run uvicorn somai_chat.main:app --reload --host 0.0.0.0 --port 8000

format:
	$(PYTHON) -m ruff format .

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest -q

check: lint typecheck test
