# Tavily Web Search Implementation Plan

> **For agentic workers:** Execute task-by-task with TDD and verify each checkpoint.

**Goal:** Add an optional Tavily-backed `web_search` tool to Somai while preserving provider-neutral application boundaries.

**Architecture:** A new `web` module owns the Tavily HTTP client and LangChain tool adapter. Central `Settings` supplies the endpoint, secret key, timeout, and result limits; the composition root creates and closes the client and injects the tool into the existing graph. Search failures become bounded safe tool results.

**Tech Stack:** Python 3.12, Pydantic Settings, httpx, LangChain tools, LangGraph, pytest.

---

### Task 1: Add configuration and web module contract

**Files:** `src/somai_chat/core/config.py`, `.env.example`, `src/somai_chat/web/search.py`, `src/somai_chat/web/AGENTS.md`, `tests/unit/test_config.py`, `tests/unit/test_web_search.py`

- [x] Add failing tests for optional Tavily settings and bounded result normalization/error behavior.
- [x] Run targeted tests and confirm they fail for missing settings/module.
- [x] Implement a small async `TavilyClient` using `httpx.AsyncClient`, POST `/search`, API key header, and a `create_web_search_tool` adapter.
- [x] Add module documentation and configuration examples.
- [x] Run targeted tests and confirm green.

### Task 2: Wire the tool into application composition

**Files:** `src/somai_chat/main.py`, `tests/unit/test_main.py`, `tests/integration/test_app.py`

- [x] Add coverage proving configured Tavily creates a tool and missing configuration keeps the app usable without search.
- [x] Instantiate/close the Tavily HTTP client only when configured and include `web_search` in graph tools.
- [x] Run focused integration tests and confirm green.

### Task 3: Full verification and documentation

**Files:** `README.md`, `src/somai_chat/agent/AGENTS.md`

- [x] Document environment variables, activation behavior, and source-link output expectations.
- [x] Run `make check` and targeted distribution tests; existing unrelated integration/config and format baseline issues are recorded in handoff.
