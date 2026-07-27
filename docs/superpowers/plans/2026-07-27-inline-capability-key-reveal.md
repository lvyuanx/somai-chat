# Inline Capability Key Reveal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a revealed capability API Key inside its existing input while preserving the distinction between viewing and replacing the Key.

**Architecture:** Pure state helpers compute the visible input value and convert user input into a replacement only after editing. The Vue component uses explicit one-way display binding plus an input handler, while the save payload continues to read only `replacement_api_key`.

**Tech Stack:** Vue 3, Element Plus, native JavaScript ES modules, Node.js assertions, Vite, pytest.

---

### Task 1: Define safe input-display state transitions

**Files:**
- Modify: `frontend/admin/src/capability-state.js`
- Modify: `tests/js/admin_capability_state.mjs`

- [ ] **Step 1: Write failing state tests**

Add these assertions:

```javascript
import {
  capabilityKeyInputValue,
  createCapabilityDraft,
  createUpdatePayload,
  updateCapabilityKeyInput,
} from "../../frontend/admin/src/capability-state.js";

const revealed = createCapabilityDraft(weather);
revealed.revealed_api_key = "original-secret";
assert.equal(capabilityKeyInputValue(revealed), "original-secret");
assert.equal("api_key" in createUpdatePayload(revealed), false);

updateCapabilityKeyInput(revealed, "edited-secret");
assert.equal(revealed.revealed_api_key, "");
assert.equal(revealed.replacement_api_key, "edited-secret");
assert.equal(createUpdatePayload(revealed).api_key, "edited-secret");
```

Also assert that a draft with neither reveal nor replacement returns an empty display value.

- [ ] **Step 2: Run the Node harness and verify RED**

Run:

```bash
node tests/js/admin_capability_state.mjs
```

Expected: import failure because the two helper exports do not exist.

- [ ] **Step 3: Implement minimal pure helpers**

```javascript
export function capabilityKeyInputValue(draft) {
  return draft.revealed_api_key || draft.replacement_api_key;
}

export function updateCapabilityKeyInput(draft, value) {
  draft.revealed_api_key = "";
  draft.replacement_api_key = value;
  draft.clear_api_key = false;
}
```

Do not change `createUpdatePayload`: it must continue serializing only `replacement_api_key`.

- [ ] **Step 4: Run the Node harness and verify GREEN**

Run the Step 2 command. Expected: the harness prints `admin capability state harness passed` and exits 0.

### Task 2: Render revealed text in the existing input

**Files:**
- Modify: `frontend/admin/src/CapabilityManagement.vue`
- Modify: `frontend/admin/src/capability-cards.css`
- Modify: `frontend/admin/AGENTS.md`
- Modify: `tests/integration/test_admin_web.py`
- Regenerate: `src/somai_chat/admin_web/dist/`

- [ ] **Step 1: Write a failing source-level interaction test**

Add assertions that `CapabilityManagement.vue` uses `:model-value="capabilityKeyInputValue(draft)"`, switches input type based on
`draft.revealed_api_key`, handles `@input` through `updateCapabilityKeyInput`, and no longer contains `revealed-secret`.

- [ ] **Step 2: Run the focused integration test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_admin_web.py -q
```

Expected: the new assertions fail against the current `v-model` and separate `<code>` output.

- [ ] **Step 3: Update the component**

Import both state helpers and replace the Key input binding with:

```vue
<el-input
  :model-value="capabilityKeyInputValue(draft)"
  :type="draft.revealed_api_key ? 'text' : 'password'"
  :show-password="!draft.revealed_api_key"
  :placeholder="draft.clear_api_key ? '保存后将清除' : draft.api_key_masked || '输入 API Key'"
  @input="updateCapabilityKeyInput(draft, $event)"
/>
```

Delete the separate revealed `<code>` element and remove `.revealed-secret` CSS. Keep `revealKey()` toggle behavior: hiding clears only
`revealed_api_key`, while `clearKey()` clears both reveal and replacement states.

- [ ] **Step 4: Synchronize frontend module documentation**

Document that reveal renders in the input, view-only plaintext is not serialized, and editing converts it into a replacement.

- [ ] **Step 5: Run complete verification**

```bash
node tests/js/admin_capability_state.mjs
.venv/bin/python -m pytest tests/integration/test_admin_web.py -q
npm --prefix frontend/admin run build
make check
git diff --check
```

Expected: all commands pass; only existing Starlette/httpx deprecation and Vite chunk-size warnings may remain.

- [ ] **Step 6: Commit only feature files**

Do not stage the pre-existing `.env.example` modification.

```bash
git add frontend/admin/src/capability-state.js frontend/admin/src/CapabilityManagement.vue \
  frontend/admin/src/capability-cards.css frontend/admin/AGENTS.md tests/js/admin_capability_state.mjs \
  tests/integration/test_admin_web.py
git add -u src/somai_chat/admin_web/dist
git add -f src/somai_chat/admin_web/dist/assets src/somai_chat/admin_web/dist/index.html
git commit -m "fix(admin): reveal capability Key inside input"
```
