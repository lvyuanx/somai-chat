# TTS Friendly Responses Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every SOMAI reply concise, natural, speakable plain text without sources, URLs, or complex formatting.

**Architecture:** Strengthen the stable system prompt and remove the conflicting search-source instruction. Extend the existing application-layer `TextNormalizer` as a deterministic fallback that removes Markdown links and bare HTTP(S) or `www` URLs before WebSocket events are emitted.

**Tech Stack:** Python 3.12, pytest, Ruff, mypy, LangGraph application pipeline.

---

### Task 1: Enforce the response policy in the system prompt

**Files:**
- Modify: `tests/unit/test_prompts.py`
- Modify: `src/somai_chat/agent/prompts.py`
- Modify: `src/somai_chat/agent/AGENTS.md`

- [x] **Step 1: Write the failing prompt test**

Add assertions that the identity explicitly bans sources and URLs and that runtime search guidance no longer asks for them:

```python
def test_prompt_requires_user_language_and_tts_friendly_output() -> None:
    assert "使用用户当前使用的语言" in SOMAI_IDENTITY
    assert "短句" in SOMAI_IDENTITY
    assert "口语化" in SOMAI_IDENTITY
    assert "TTS" in SOMAI_IDENTITY
    assert "禁止使用 Markdown" in SOMAI_IDENTITY
    assert "不要输出来源名称或网址" in SOMAI_IDENTITY
    assert "列出主要来源名称和网址" not in RUNTIME_CAPABILITIES
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/unit/test_prompts.py -q`

Expected: FAIL because the new stable response policy is absent and the conflicting search-source instruction remains.

- [x] **Step 3: Apply the minimal prompt change**

Update `SOMAI_IDENTITY` to require short, natural, speakable text and prohibit source names and URLs. Replace the search response rule with:

```python
"回答使用搜索结果的问题时，综合多个结果后直接给出简短、自然的结论；不要输出来源名称或网址。"
```

Document the stable TTS response boundary in `src/somai_chat/agent/AGENTS.md`.

- [x] **Step 4: Run the focused test and verify GREEN**

Run: `uv run pytest tests/unit/test_prompts.py -q`

Expected: all prompt tests pass.

### Task 2: Remove URLs at the application output boundary

**Files:**
- Modify: `tests/unit/test_text_normalizer.py`
- Modify: `src/somai_chat/application/text_normalizer.py`
- Modify: `src/somai_chat/application/AGENTS.md`

- [x] **Step 1: Write failing normalizer tests**

Add a test proving link labels remain while destinations and bare URLs are removed:

```python
def test_normalizer_removes_markdown_destinations_and_bare_urls() -> None:
    normalizer = TextNormalizer()

    text = normalizer.normalize(
        "详情见 [新华网](https://news.example/a) 或 https://example.com/x，也可访问 www.example.org。"
    )

    assert "新华网" in text
    assert "https://" not in text
    assert "www." not in text
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/unit/test_text_normalizer.py -q`

Expected: FAIL because bare HTTP(S) and `www` URLs remain.

- [x] **Step 3: Apply the minimal normalizer change**

Add a compiled URL pattern alongside the existing Markdown link pattern:

```python
_bare_url = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>，。！？；：、]+")
```

After replacing Markdown links with their labels, replace bare URLs with an empty string. Document URL removal in `src/somai_chat/application/AGENTS.md`.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/unit/test_prompts.py tests/unit/test_text_normalizer.py -q`

Expected: all focused tests pass.

### Task 3: Verify the complete change

**Files:**
- Verify all modified source, tests, and module documentation.

- [x] **Step 1: Inspect the diff and formatting**

Run: `git diff --check && git diff --stat`

Expected: no whitespace errors and only planned files changed.

- [x] **Step 2: Run the repository quality suite**

Run: `make check`

Expected: Ruff, strict mypy, and the complete pytest suite all pass.

- [x] **Step 3: Confirm requirement coverage**

Run: `rg -n "列出主要来源名称和网址|不要输出来源名称或网址|_bare_url" src tests`

Expected: the old conflicting instruction is absent; the new prompt policy, fallback normalizer, and tests are present.
