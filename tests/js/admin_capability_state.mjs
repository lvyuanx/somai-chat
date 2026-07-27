import assert from "node:assert/strict";
import {
  createCapabilityDraft,
  createUpdatePayload,
  validateCapabilityDraft,
} from "../../frontend/admin/src/capability-state.js";

const weather = {
  key: "weather",
  enabled: true,
  configuration: { api_host: "https://weather.example", timeout_seconds: 5 },
  api_key_masked: "••••••••-key",
  can_reveal_api_key: true,
};

assert.equal("api_key" in createUpdatePayload(createCapabilityDraft(weather)), false);
const replacement = createCapabilityDraft(weather);
replacement.replacement_api_key = "replacement-key";
assert.equal(createUpdatePayload(replacement).api_key, "replacement-key");
const missing = createCapabilityDraft({ ...weather, can_reveal_api_key: false });
assert.match(validateCapabilityDraft(missing), /API Key/);
console.log("admin capability state harness passed");
