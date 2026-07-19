import {codePointLength, createConsoleView} from "./view.js";
(() => {
  "use strict";

  if (new URLSearchParams(window.location.search).has("embed")) {
    document.body.classList.add("embedded");
  }

  const DEFAULT_MAX_MESSAGE_LENGTH = 8000;
  const DEFAULT_MAX_FRAME_BYTES = 32768;
  const MAX_RECONNECT_ATTEMPTS = 5;
  const TIMING_REFRESH_MS = 100;
  const CONVERSATION_PATTERN = /^conv_[A-Za-z0-9_-]{1,123}$/;
  const STORAGE_KEY = "somai.conversation_id";
  const elements = {
    composer: document.getElementById("composer"),
    input: document.getElementById("message-input"),
    imageInput: document.getElementById("image-input"),
    imageSelect: document.getElementById("image-select"),
    imageName: document.getElementById("image-name"),
    imagePreview: document.getElementById("image-preview"),
    sendStop: document.getElementById("send-stop"),
    timeline: document.getElementById("message-timeline"),
    trace: document.getElementById("event-trace"),
    status: document.getElementById("connection-status"),
    conversationId: document.getElementById("conversation-id"),
    model: document.getElementById("model-name"),
    count: document.getElementById("character-count"),
    hint: document.getElementById("composer-hint"),
    liveStatus: document.getElementById("live-status"),
    newSession: document.getElementById("new-session"),
    clearDisplay: document.getElementById("clear-display"),
  };
  const view = createConsoleView({
    document,
    window,
    elements: {timeline: elements.timeline, trace: elements.trace, liveStatus: elements.liveStatus},
    limits: {responseCodePoints: 100000, timelineMessages: 100, traceEvents: 120, traceCodePoints: 12000},
  });
  const state = {
    conversationId: restoreConversationId(),
    socket: null,
    connection: "connecting",
    maxMessageLength: DEFAULT_MAX_MESSAGE_LENGTH,
    maxFrameBytes: DEFAULT_MAX_FRAME_BYTES,
    phase: "idle",
    pendingMessageId: null,
    activeResponseId: null,
    requestStartedAt: null,
    firstTokenAt: null,
    timingTimer: null,
    reconnectAttempts: 0,
    reconnectTimer: null,
    intentionalClose: false,
    messageSequence: 0,
    imageUrl: null,
    imageDisplayUrl: null,
    uploadingImage: false,
    imagePreviewUrl: null,
  };
  function randomToken() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID().replaceAll("-", "");
    }
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  }

  function createConversationId() {
    return `conv_${randomToken()}`.slice(0, 128);
  }
  function restoreConversationId() {
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved && CONVERSATION_PATTERN.test(saved)) {
        return saved;
      }
    } catch (_error) {
      // Storage can be unavailable in privacy modes; the in-memory ID remains valid.
    }
    return createConversationId();
  }

  function persistConversationId() {
    try {
      window.localStorage.setItem(STORAGE_KEY, state.conversationId);
    } catch (_error) {
      // A functioning chat connection does not depend on persistent browser storage.
    }
  }
  function setStatus(label, kind) {
    const lamp = document.createElement("span");
    lamp.className = "status-lamp";
    lamp.setAttribute("aria-hidden", "true");
    while (elements.status.firstChild) {
      elements.status.removeChild(elements.status.firstChild);
    }
    elements.status.append(lamp, document.createTextNode(label));
    elements.status.dataset.state = kind;
    state.connection = kind;
    updateControls();
  }

  function showLocalError(message) {
    view.appendMessage("system", message, {error: true});
    view.announce(`Error: ${message}`);
  }

  function updateControls() {
    const hasContent = codePointLength(elements.input.value.trim()) > 0;
    const ready = state.connection === "ready";
    const label = state.phase === "pending" ? "Waiting"
      : state.phase === "streaming" ? "Stop"
        : state.phase === "cancelling" ? "Stopping" : "Send";
    elements.sendStop.textContent = label;
    elements.sendStop.dataset.mode = state.phase === "streaming" ? "stop" : "send";
    elements.sendStop.disabled = state.phase === "pending" || state.phase === "cancelling"
      ? true
      : state.phase === "streaming" ? !state.activeResponseId : !ready || !hasContent || state.uploadingImage;
    elements.input.disabled = state.phase !== "idle";
    if (elements.imageSelect) elements.imageSelect.disabled = state.phase !== "idle" || state.uploadingImage;
    elements.clearDisplay.disabled = state.phase !== "idle";
  }

  function resetRequestState() {
    stopTimingUpdates();
    view.discardAssistant();
    state.phase = "idle";
    state.pendingMessageId = null;
    state.activeResponseId = null;
    state.requestStartedAt = null;
    state.firstTokenAt = null;
  }

  function finishGeneration(label, error = false) {
    updateAssistantTiming();
    stopTimingUpdates();
    view.finishAssistant();
    resetRequestState();
    if (label) {
      view.appendMessage("system", label, {error});
    }
    updateControls();
    elements.input.focus();
  }

  function updateAssistantTiming() {
    if (state.requestStartedAt === null) {
      return;
    }
    view.updateAssistantTiming({now: Date.now(), firstTokenAt: state.firstTokenAt});
  }

  function startTimingUpdates() {
    stopTimingUpdates();
    updateAssistantTiming();
    state.timingTimer = window.setInterval(updateAssistantTiming, TIMING_REFRESH_MS);
  }

  function stopTimingUpdates() {
    if (state.timingTimer !== null) {
      window.clearInterval(state.timingTimer);
      state.timingTimer = null;
    }
  }

  function recordFirstToken() {
    if (state.firstTokenAt === null) {
      state.firstTokenAt = Date.now();
    }
    updateAssistantTiming();
  }

  function applyReadyLimits(data) {
    state.maxMessageLength = Number.isInteger(data.max_message_length) && data.max_message_length > 0
      ? data.max_message_length : DEFAULT_MAX_MESSAGE_LENGTH;
    state.maxFrameBytes = Number.isInteger(data.max_websocket_message_bytes)
      && data.max_websocket_message_bytes > 0
      ? data.max_websocket_message_bytes : DEFAULT_MAX_FRAME_BYTES;
    const count = codePointLength(elements.input.value);
    elements.count.textContent = `${count} / ${state.maxMessageLength}`;
    elements.hint.textContent = `Enter to send · Shift + Enter for line break · Limit ${state.maxMessageLength}`;
  }

  function matchesActiveResponse(data) {
    return typeof data.response_id === "string" && data.response_id === state.activeResponseId;
  }

  function handleEvent(event) {
    if (!event || typeof event !== "object" || typeof event.type !== "string") {
      showLocalError("Ignored malformed server event.");
      return;
    }
    const data = event.data && typeof event.data === "object" ? event.data : {};
    if (event.type === "conversation.ready") {
      state.reconnectAttempts = 0;
      applyReadyLimits(data);
      elements.model.textContent = typeof data.model === "string" ? data.model : "configured runtime";
      setStatus("Ready", "ready");
      view.announce("Conversation ready.");
    } else if (event.type === "response.started") {
      if (state.phase !== "pending" || data.message_id !== state.pendingMessageId) {
        return;
      }
      if (typeof data.response_id !== "string") {
        return;
      }
      state.pendingMessageId = null;
      state.activeResponseId = data.response_id;
      state.phase = "streaming";
      view.startAssistant({requestStartedAt: state.requestStartedAt});
      startTimingUpdates();
      updateControls();
    } else if (event.type === "response.delta" && matchesActiveResponse(data)) {
      if (typeof data.delta === "string") {
        if (data.delta) {
          recordFirstToken();
        }
        view.appendAssistantDelta(data.delta);
      }
    } else if (event.type === "response.completed" && matchesActiveResponse(data)) {
      if (typeof data.content === "string") {
        if (data.content) {
          recordFirstToken();
        }
        view.replaceAssistantContent(data.content);
      }
      finishGeneration("");
      view.announce("Response completed.");
    } else if (event.type === "response.cancelled" && matchesActiveResponse(data)) {
      finishGeneration("Generation stopped.");
      view.announce("Response stopped.");
    } else if (event.type === "error") {
      const message = typeof data.message === "string" ? data.message : "The request could not be completed.";
      const matchesPendingError = state.phase === "pending" && data.message_id === state.pendingMessageId;
      const matchesActiveError = state.phase !== "idle" && matchesActiveResponse(data);
      if (matchesPendingError || matchesActiveError) {
        finishGeneration(message, true);
      } else {
        view.appendMessage("system", message, {error: true});
      }
      view.announce(`Error: ${message}`);
    }
  }

  function socketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/api/v1/chat/ws/${state.conversationId}`;
  }

  function connect() {
    clearTimeout(state.reconnectTimer);
    state.intentionalClose = false;
    setStatus(state.reconnectAttempts ? "Reconnecting" : "Connecting", "connecting");
    const socket = new WebSocket(socketUrl());
    state.socket = socket;
    socket.addEventListener("message", (message) => {
      if (state.socket !== socket) {
        return;
      }
      let event;
      try {
        event = JSON.parse(message.data);
      } catch (_error) {
        showLocalError("Received an unreadable server event.");
        return;
      }
      view.appendTrace("RX", event);
      handleEvent(event);
    });
    socket.addEventListener("close", () => {
      if (state.socket !== socket) {
        return;
      }
      state.socket = null;
      if (state.phase !== "idle") {
        finishGeneration("Connection closed; the last message was not replayed.", true);
        view.announce("Error: Connection closed; the last message was not replayed.");
      } else {
        resetRequestState();
      }
      if (state.intentionalClose) {
        return;
      }
      if (state.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        setStatus("Offline", "error");
        showLocalError("Reconnect limit reached. Start a new session to retry.");
        return;
      }
      state.reconnectAttempts += 1;
      const delay = Math.min(8000, 500 * (2 ** (state.reconnectAttempts - 1)));
      setStatus(`Retry ${state.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}`, "connecting");
      state.reconnectTimer = window.setTimeout(connect, delay);
    });
    socket.addEventListener("error", () => {
      if (state.socket !== socket) {
        return;
      }
      setStatus("Link error", "error");
      view.announce("Error: WebSocket link error.");
    });
  }

  function sendEvent(event, serialized = JSON.stringify(event)) {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      showLocalError("Connection is not ready.");
      return false;
    }
    view.appendTrace("TX", event);
    state.socket.send(serialized);
    return true;
  }

  function submitMessage() {
    if (state.phase === "pending" || state.phase === "cancelling") {
      return;
    }
    if (state.phase === "streaming" && state.activeResponseId) {
      const cancelEvent = {type: "response.cancel", data: {response_id: state.activeResponseId}};
      if (sendEvent(cancelEvent)) {
        state.phase = "cancelling";
        updateControls();
      }
      return;
    }
    if (state.phase !== "idle") {
      return;
    }
    const content = elements.input.value.trim();
    const contentLength = codePointLength(content);
    if (!content || state.connection !== "ready") {
      return;
    }
    if (contentLength > state.maxMessageLength) {
      showLocalError(`Message exceeds the ${state.maxMessageLength} code point limit.`);
      return;
    }
    state.messageSequence += 1;
    const messageId = `msg_${randomToken()}_${state.messageSequence}`.slice(0, 128);
    const data = {message_id: messageId, content};
    if (state.imageUrl) {
      data.image_urls = [state.imageUrl];
    }
    const event = {type: "message.create", data};
    const serialized = JSON.stringify(event);
    if (new TextEncoder().encode(serialized).byteLength > state.maxFrameBytes) {
      showLocalError(`Message frame exceeds the ${state.maxFrameBytes} byte limit.`);
      return;
    }
    if (sendEvent(event, serialized)) {
      state.pendingMessageId = messageId;
      state.requestStartedAt = Date.now();
      state.phase = "pending";
      view.appendMessage("user", content, {imageSource: state.imageDisplayUrl});
      elements.input.value = "";
      state.imageUrl = null;
      state.imageDisplayUrl = null;
      state.imagePreviewUrl = null;
      if (elements.imageInput && elements.imagePreview) {
        elements.imageInput.value = "";
        elements.imagePreview.hidden = true;
        elements.imagePreview.removeAttribute("src");
      }
      if (elements.imageName) elements.imageName.textContent = "";
      elements.count.textContent = `0 / ${state.maxMessageLength}`;
      updateControls();
    }
  }

  elements.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage();
  });
  elements.input.addEventListener("input", () => {
    elements.count.textContent = `${codePointLength(elements.input.value)} / ${state.maxMessageLength}`;
    updateControls();
  });
  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  });
  if (elements.imageSelect && elements.imageInput && elements.imageName && elements.imagePreview) {
    elements.imageSelect.addEventListener("click", () => elements.imageInput.click());
    elements.imageInput.addEventListener("change", async () => {
    const [file] = elements.imageInput.files;
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      state.imagePreviewUrl = typeof reader.result === "string" ? reader.result : null;
      if (state.imagePreviewUrl) elements.imagePreview.src = state.imagePreviewUrl;
    };
    reader.readAsDataURL(file);
    elements.imagePreview.hidden = false;
    state.uploadingImage = true;
    elements.imageName.textContent = "Uploading image...";
    updateControls();
    const body = new FormData();
    body.append("image", file);
    try {
      const response = await fetch("/api/v1/images", {method: "POST", body});
      const payload = await response.json();
      if (!response.ok || typeof payload.image_url !== "string") throw new Error();
      state.imageUrl = new URL(payload.image_url, window.location.origin).href;
      state.imageDisplayUrl = payload.image_url;
      elements.imageName.textContent = file.name;
    } catch (_error) {
      state.imageUrl = null;
      state.imageDisplayUrl = null;
      state.imagePreviewUrl = null;
      elements.imageInput.value = "";
      elements.imagePreview.hidden = true;
      elements.imagePreview.removeAttribute("src");
      elements.imageName.textContent = "Image upload failed.";
    } finally {
      state.uploadingImage = false;
      updateControls();
    }
    });
  }
  elements.newSession.addEventListener("click", () => {
    state.intentionalClose = true;
    clearTimeout(state.reconnectTimer);
    if (state.socket) {
      state.socket.close(1000, "new session");
    }
    state.conversationId = createConversationId();
    state.reconnectAttempts = 0;
    resetRequestState();
    elements.conversationId.textContent = state.conversationId;
    view.clearDisplay();
    persistConversationId();
    view.appendMessage("system", "New local session created.");
    connect();
  });
  elements.clearDisplay.addEventListener("click", () => {
    if (state.phase !== "idle") {
      return;
    }
    view.clearDisplay();
    view.appendMessage("system", "Local display cleared; server conversation state is unchanged.");
  });
  window.addEventListener("beforeunload", () => {
    state.intentionalClose = true;
    clearTimeout(state.reconnectTimer);
    if (state.socket) {
      state.socket.close(1000, "page unload");
    }
  });

  elements.conversationId.textContent = state.conversationId;
  persistConversationId();
  view.appendMessage("system", "Diagnostic channel initialized. Waiting for runtime readiness.");
  updateControls();
  connect();
})();
