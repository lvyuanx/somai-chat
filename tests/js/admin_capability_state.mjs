import assert from "node:assert/strict";
import {
  capabilityKeyInputValue,
  clearCapabilityKeyInput,
  createCapabilityDraft,
  createUpdatePayload,
  handleCapabilityKeydown,
  updateCapabilityKeyInput,
  validateCapabilityDraft,
} from "../../frontend/admin/src/capability-state.js";

const weather = {
  key: "weather",
  enabled: true,
  configuration: { api_host: "https://weather.example", timeout_seconds: 5 },
  api_key_masked: "••••••••-key",
  can_reveal_api_key: true,
};

const reactiveLikeWeather = new Proxy(
  { ...weather, configuration: new Proxy(weather.configuration, {}) },
  {},
);
assert.deepEqual(createCapabilityDraft(reactiveLikeWeather).configuration, weather.configuration);
assert.deepEqual(createUpdatePayload(createCapabilityDraft(reactiveLikeWeather)).configuration, weather.configuration);
assert.equal("api_key" in createUpdatePayload(createCapabilityDraft(weather)), false);
const replacement = createCapabilityDraft(weather);
replacement.replacement_api_key = "replacement-key";
assert.equal(createUpdatePayload(replacement).api_key, "replacement-key");
const cleared = createCapabilityDraft(weather);
cleared.revealed_api_key = "revealed-secret";
cleared.replacement_api_key = "typed-secret";
clearCapabilityKeyInput(cleared);
assert.equal(cleared.revealed_api_key, "");
assert.equal(cleared.replacement_api_key, "");
assert.equal(cleared.api_key_masked, "");
assert.equal(cleared.clear_api_key, false);
assert.equal("api_key" in createUpdatePayload(cleared), false);
const keyboardCleared = createCapabilityDraft(weather);
keyboardCleared.replacement_api_key = "typed-secret";
let preventDefaultCalled = false;
handleCapabilityKeydown(keyboardCleared, {
  key: "Delete",
  preventDefault() {
    preventDefaultCalled = true;
  },
});
assert.equal(preventDefaultCalled, true);
assert.equal(keyboardCleared.replacement_api_key, "");
assert.equal(keyboardCleared.revealed_api_key, "");
const revealed = createCapabilityDraft(weather);
revealed.revealed_api_key = "original-secret";
assert.equal(capabilityKeyInputValue(revealed), "original-secret");
assert.equal("api_key" in createUpdatePayload(revealed), false);
updateCapabilityKeyInput(revealed, "edited-secret");
assert.equal(revealed.revealed_api_key, "");
assert.equal(revealed.replacement_api_key, "edited-secret");
assert.equal(createUpdatePayload(revealed).api_key, "edited-secret");
assert.equal(capabilityKeyInputValue(createCapabilityDraft(weather)), "");
const missing = createCapabilityDraft({ ...weather, can_reveal_api_key: false });
assert.match(validateCapabilityDraft(missing), /API Key/);
console.log("admin capability state harness passed");
