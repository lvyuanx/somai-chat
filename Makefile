.PHONY: install dev format lint typecheck test check

PYTHON := .venv/bin/python

install:
	uv sync --locked --extra dev

dev:
	uv run python -m somai_chat.main

format:
	$(PYTHON) -m ruff format .

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest -q

check: lint typecheck test
