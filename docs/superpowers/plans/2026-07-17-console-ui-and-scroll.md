# Console UI and Smart Scroll Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a dark, focused SOMAI console whose conversation timeline always scrolls correctly and follows new content only when the reader is near the bottom.

**Architecture:** Keep the current framework-free HTML/CSS/DOM design and WebSocket protocol unchanged. Make the conversation panel's grid child shrinkable, confine vertical scrolling to the timeline, and centralize the 48px near-bottom decision in `view.js` before each timeline mutation or streaming render.

**Tech Stack:** Native HTML/CSS, ES modules, Node assertion harnesses, FastAPI integration tests, Ruff, mypy, pytest.

---

## File structure

- `src/somai_chat/web/app.css`: desktop dark visual tokens, component styling, and grid/minimum-size constraints.
- `src/somai_chat/web/responsive.css`: mobile visual adjustments and timeline containment.
- `src/somai_chat/web/view.js`: testable near-bottom measurement and conditional timeline following.
- `tests/js/console_view.mjs`: lightweight DOM regression tests for scroll behavior.
- `tests/integration/test_web_console.py`: static asset contract assertions for the scroll containment and dark theme.
- `src/somai_chat/web/AGENTS.md`: updated module description of the new visual and scroll behavior.

### Task 1: Prove smart-follow behavior in the view harness

**Files:**
- Modify: `tests/js/console_view.mjs:7-46, 94-137`
- Modify: `src/somai_chat/web/view.js:1-112`

- [ ] **Step 1: Write the failing near-bottom tests and DOM measurements**

  Extend `Node` with deterministic scroll geometry and append the following checks after importing the view:

  ```js
  elements.timeline.clientHeight = 100;
  elements.timeline.scrollHeight = 200;
  elements.timeline.scrollTop = 51;
  view.appendMessage("system", "follow-me");
  assert(elements.timeline.scrollTop === elements.timeline.scrollHeight, "near-bottom reader did not follow");

  elements.timeline.scrollHeight = 400;
  elements.timeline.scrollTop = 120;
  view.appendMessage("system", "keep-reading");
  assert(elements.timeline.scrollTop === 120, "history reader was pulled to the bottom");
  ```

  Make the harness's `scrollHeight` settable by backing it with `_scrollHeight`; retain its child-count default when no explicit height has been supplied.

- [ ] **Step 2: Run the focused harness to verify it fails**

  Run: `node tests/js/console_view.mjs`

  Expected: FAIL with `history reader was pulled to the bottom`, because the existing view assigns `scrollTop = scrollHeight` unconditionally.

- [ ] **Step 3: Implement the minimal near-bottom helper and use it for timeline rendering**

  Add a module-level threshold and helper to `view.js`:

  ```js
  const FOLLOW_THRESHOLD_PX = 48;

  function shouldFollowTimeline(timeline) {
    return timeline.scrollHeight - timeline.clientHeight - timeline.scrollTop <= FOLLOW_THRESHOLD_PX;
  }
  ```

  In `appendMessage`, capture `const shouldFollow = shouldFollowTimeline(elements.timeline);` before appending and only assign `scrollTop` after trimming if `shouldFollow` is true. In `renderAssistant`, make the same capture before replacing the body and conditionally follow afterward. Do not change trace following.

- [ ] **Step 4: Run the focused harness to verify it passes**

  Run: `node tests/js/console_view.mjs`

  Expected: `console view boundary harness passed`.

- [ ] **Step 5: Commit the behavior change**

  ```bash
  git add tests/js/console_view.mjs src/somai_chat/web/view.js
  git commit -m "fix: preserve chat history scroll position"
  ```

### Task 2: Add regression coverage for scroll containment

**Files:**
- Modify: `tests/integration/test_web_console.py:105-126`
- Modify: `src/somai_chat/web/app.css:40-220`
- Modify: `src/somai_chat/web/responsive.css:1-75`

- [ ] **Step 1: Write failing static style assertions**

  Add assertions to `test_console_styles_cover_responsive_accessible_streaming_states`:

  ```python
  assert ".conversation-panel" in css
  assert "grid-template-rows: auto minmax(0, 1fr) auto" in css
  assert ".message-timeline" in css and "overflow-y: auto" in css
  assert "min-height: 0" in css
  assert "min-height: 0" in mobile
  assert "--surface-base" in css
  ```

- [ ] **Step 2: Run the focused integration test to verify it fails**

  Run: `uv run pytest tests/integration/test_web_console.py::test_console_styles_cover_responsive_accessible_streaming_states -q`

  Expected: FAIL because `--surface-base` does not yet exist.

- [ ] **Step 3: Make the minimal containment changes**

  Define `--surface-base` in the root token block, update `.conversation-panel` to include `min-height: 0`, and retain its existing three-row template. Ensure `.message-timeline` keeps `overflow-y: auto`. In the mobile media query, keep `.conversation-panel { min-height: 0; }` and set the timeline's flex/grid descendants to be shrinkable if needed; do not add document-level scrolling.

- [ ] **Step 4: Run the focused integration test to verify it passes**

  Run: `uv run pytest tests/integration/test_web_console.py::test_console_styles_cover_responsive_accessible_streaming_states -q`

  Expected: `1 passed`.

- [ ] **Step 5: Commit the containment contract**

  ```bash
  git add tests/integration/test_web_console.py src/somai_chat/web/app.css src/somai_chat/web/responsive.css
  git commit -m "fix: contain console timeline scrolling"
  ```

### Task 3: Apply the approved dark visual system

**Files:**
- Modify: `src/somai_chat/web/app.css:1-425`
- Modify: `src/somai_chat/web/responsive.css:1-75`

- [ ] **Step 1: Extend the existing static test with dark-theme tokens**

  Require the new surface and accent contract:

  ```python
  assert "--surface-base: #0d1523" in css
  assert "--surface-raised: #162238" in css
  assert "--accent-blue: #1f75fe" in css
  assert "border-radius: 14px" in css
  ```

- [ ] **Step 2: Run the focused integration test to verify it fails**

  Run: `uv run pytest tests/integration/test_web_console.py::test_console_styles_cover_responsive_accessible_streaming_states -q`

  Expected: FAIL because the exact dark tokens and rounded-card treatment are absent.

- [ ] **Step 3: Replace visual declarations without changing selectors or markup**

  Update CSS variables and existing component rules as follows:

  ```css
  :root {
    --surface-base: #0d1523;
    --surface-raised: #162238;
    --surface-panel: #101b2e;
    --text-primary: #e7efff;
    --text-muted: #91a3bf;
    --line: #2d405d;
    --accent-blue: #1f75fe;
    --success-green: #4bcf91;
    --error-red: #ff6678;
  }
  ```

  Use `--surface-base` for the body and conversation background, `--surface-raised` for rails and composer, and `--accent-blue` for the primary action, focus outline, assistant label, and streaming cursor. Give the console shell, controls, composer, and user message cards a consistent `14px` radius. Preserve contrast, disabled states, reduced-motion behavior, and no external assets.

- [ ] **Step 4: Run the focused tests to verify they pass**

  Run: `uv run pytest tests/integration/test_web_console.py -q && node tests/js/console_view.mjs && node tests/js/web_console_state.mjs`

  Expected: all tests pass and both Node harnesses print their success lines.

- [ ] **Step 5: Commit the visual refresh**

  ```bash
  git add src/somai_chat/web/app.css src/somai_chat/web/responsive.css tests/integration/test_web_console.py
  git commit -m "feat: refresh console dark interface"
  ```

### Task 4: Synchronize module documentation and verify the repository

**Files:**
- Modify: `src/somai_chat/web/AGENTS.md:10-61`

- [ ] **Step 1: Update the module contract**

  Replace the statement that desktop uses an “industrial equipment console” with a dark, focused three-column workspace. Document that the timeline is the sole conversation scroller and that it follows only when the reader is within 48px of the bottom.

- [ ] **Step 2: Run targeted quality checks**

  Run: `make format && make lint && make typecheck && make test`

  Expected: all commands exit 0.

- [ ] **Step 3: Inspect the final diff**

  Run: `git diff --check HEAD~3..HEAD && git status --short`

  Expected: no whitespace errors; only the intended UI, view, test, and module-documentation files are modified or committed. Preserve the user-owned untracked root `AGENTS.md`.

- [ ] **Step 4: Commit the documentation update**

  ```bash
  git add src/somai_chat/web/AGENTS.md
  git commit -m "docs: describe console scrolling behavior"
  ```
