export function createCapabilityDraft(view) {
  return {
    ...structuredClone(view),
    replacement_api_key: "",
    revealed_api_key: "",
    clear_api_key: false,
    saving: false,
    error: "",
  };
}

export function createUpdatePayload(draft) {
  const payload = {
    enabled: draft.enabled,
    configuration: structuredClone(draft.configuration),
    clear_api_key: draft.clear_api_key,
  };
  const replacement = draft.replacement_api_key.trim();
  if (replacement && !draft.clear_api_key) payload.api_key = replacement;
  return payload;
}

export function validateCapabilityDraft(draft) {
  if (draft.key === "time") return "";
  const hasKey = draft.can_reveal_api_key || draft.replacement_api_key.trim();
  if (draft.enabled && (draft.clear_api_key || !hasKey)) return "请先配置 API Key 再开启能力";
  try {
    const url = new URL(draft.configuration.api_host);
    if (!["http:", "https:"].includes(url.protocol)) return "API Host 必须使用 HTTP(S)";
  } catch (_) {
    return "API Host 格式无效";
  }
  if (!(draft.configuration.timeout_seconds > 0)) return "请求超时必须大于 0";
  if (draft.key === "web_search") {
    const count = draft.configuration.max_results;
    if (!Number.isInteger(count) || count < 1 || count > 20) return "最大结果数必须为 1 到 20";
  }
  return "";
}
