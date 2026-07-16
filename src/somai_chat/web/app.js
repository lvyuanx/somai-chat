(() => {
  "use strict";

  const MAX_MESSAGE_LENGTH = 8000;
  const MAX_TRACE_EVENTS = 120;
  const MAX_RECONNECT_ATTEMPTS = 5;
  const CONVERSATION_PATTERN = /^conv_[A-Za-z0-9_-]{1,123}$/;
  const STORAGE_KEY = "somai.conversation_id";

  const elements = {
    composer: document.getElementById("composer"),
    input: document.getElementById("message-input"),
    sendStop: document.getElementById("send-stop"),
    timeline: document.getElementById("message-timeline"),
    trace: document.getElementById("event-trace"),
    status: document.getElementById("connection-status"),
    conversationId: document.getElementById("conversation-id"),
    model: document.getElementById("model-name"),
    count: document.getElementById("character-count"),
    newSession: document.getElementById("new-session"),
    clearDisplay: document.getElementById("clear-display"),
  };

  const state = {
    conversationId: restoreConversationId(),
    socket: null,
    connection: "connecting",
    generating: false,
    activeResponseId: null,
    activeAssistant: null,
    reconnectAttempts: 0,
    reconnectTimer: null,
    intentionalClose: false,
    messageSequence: 0,
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

  function appendInline(parent, source) {
    const tokenPattern = /(`[^`\n]+`|\[[^\]\n]+\]\([^\s)]+\))/g;
    let cursor = 0;
    for (const match of source.matchAll(tokenPattern)) {
      const index = match.index || 0;
      parent.append(document.createTextNode(source.slice(cursor, index)));
      const token = match[0];
      if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        parent.append(code);
      } else {
        const split = token.lastIndexOf("](");
        const label = token.slice(1, split);
        const rawUrl = token.slice(split + 2, -1);
        let safeUrl = null;
        try {
          const parsed = new URL(rawUrl);
          if (parsed.protocol === "http:" || parsed.protocol === "https:") {
            safeUrl = parsed.href;
          }
        } catch (_error) {
          safeUrl = null;
        }
        if (safeUrl) {
          const link = document.createElement("a");
          link.textContent = label;
          link.setAttribute("href", safeUrl);
          link.setAttribute("target", "_blank");
          link.setAttribute("rel", "noopener noreferrer");
          parent.append(link);
        } else {
          parent.append(document.createTextNode(label));
        }
      }
      cursor = index + token.length;
    }
    parent.append(document.createTextNode(source.slice(cursor)));
  }

  function markdownNodes(source) {
    const fragment = document.createDocumentFragment();
    const lines = source.replaceAll("\r\n", "\n").split("\n");
    let lineIndex = 0;
    let paragraph = [];

    function flushParagraph() {
      if (!paragraph.length) {
        return;
      }
      const node = document.createElement("p");
      appendInline(node, paragraph.join(" "));
      fragment.append(node);
      paragraph = [];
    }

    while (lineIndex < lines.length) {
      const line = lines[lineIndex];
      if (line.startsWith("```")) {
        flushParagraph();
        const codeLines = [];
        lineIndex += 1;
        while (lineIndex < lines.length && !lines[lineIndex].startsWith("```")) {
          codeLines.push(lines[lineIndex]);
          lineIndex += 1;
        }
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.append(code);
        fragment.append(pre);
      } else {
        const heading = /^(#{1,3})\s+(.+)$/.exec(line);
        const listItem = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(line);
        if (heading) {
          flushParagraph();
          const node = document.createElement(`h${heading[1].length}`);
          appendInline(node, heading[2]);
          fragment.append(node);
        } else if (listItem) {
          flushParagraph();
          const ordered = listItem[2].endsWith(".");
          const list = document.createElement(ordered ? "ol" : "ul");
          while (lineIndex < lines.length) {
            const item = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(lines[lineIndex]);
            if (!item || item[2].endsWith(".") !== ordered) {
              break;
            }
            const listNode = document.createElement("li");
            appendInline(listNode, item[3]);
            list.append(listNode);
            lineIndex += 1;
          }
          fragment.append(list);
          continue;
        } else if (line.trim()) {
          paragraph.push(line.trim());
        } else {
          flushParagraph();
        }
      }
      lineIndex += 1;
    }
    flushParagraph();
    return fragment;
  }

  function renderBody(body, content, streaming) {
    while (body.firstChild) {
      body.removeChild(body.firstChild);
    }
    body.append(markdownNodes(content));
    if (streaming) {
      const cursor = document.createElement("span");
      cursor.className = "streaming-cursor";
      cursor.setAttribute("aria-label", "Response streaming");
      body.append(cursor);
    }
  }

  function appendMessage(role, content, options = {}) {
    const article = document.createElement("article");
    const meta = document.createElement("div");
    const body = document.createElement("div");
    article.className = `message message--${role}${options.error ? " message--error" : ""}`;
    meta.className = "message__meta";
    meta.textContent = role === "assistant" ? "SOMAI" : role;
    body.className = "message__body";
    renderBody(body, content, Boolean(options.streaming));
    article.append(meta, body);
    elements.timeline.append(article);
    elements.timeline.scrollTop = elements.timeline.scrollHeight;
    return {article, body, content};
  }

  function appendTrace(direction, event) {
    const item = document.createElement("li");
    const directionNode = document.createElement("span");
    const payload = document.createElement("pre");
    item.className = "trace-event";
    directionNode.className = "trace-event__direction";
    directionNode.textContent = direction;
    payload.className = "trace-event__payload";
    payload.textContent = JSON.stringify(event, null, 2);
    item.append(directionNode, payload);
    elements.trace.append(item);
    while (elements.trace.childElementCount > MAX_TRACE_EVENTS) {
      elements.trace.removeChild(elements.trace.firstElementChild);
    }
    elements.trace.scrollTop = elements.trace.scrollHeight;
  }

  function updateControls() {
    const hasContent = elements.input.value.trim().length > 0;
    const ready = state.connection === "ready";
    elements.sendStop.textContent = state.generating ? "Stop" : "Send";
    elements.sendStop.dataset.mode = state.generating ? "stop" : "send";
    elements.sendStop.disabled = state.generating ? !state.activeResponseId : !ready || !hasContent;
    elements.input.disabled = state.generating;
  }

  function finishGeneration(label, error = false) {
    if (state.activeAssistant) {
      renderBody(state.activeAssistant.body, state.activeAssistant.content, false);
    }
    state.generating = false;
    state.activeResponseId = null;
    state.activeAssistant = null;
    if (label) {
      appendMessage("system", label, {error});
    }
    updateControls();
    elements.input.focus();
  }

  function handleEvent(event) {
    if (!event || typeof event !== "object" || typeof event.type !== "string") {
      appendMessage("system", "Ignored malformed server event.", {error: true});
      return;
    }
    const data = event.data && typeof event.data === "object" ? event.data : {};
    if (event.type === "conversation.ready") {
      state.reconnectAttempts = 0;
      elements.model.textContent = typeof data.model === "string" ? data.model : "configured runtime";
      setStatus("Ready", "ready");
    } else if (event.type === "response.started") {
      state.activeResponseId = typeof data.response_id === "string" ? data.response_id : null;
      state.generating = true;
      state.activeAssistant = appendMessage("assistant", "", {streaming: true});
      updateControls();
    } else if (event.type === "response.delta" && state.activeAssistant) {
      if (typeof data.delta === "string") {
        state.activeAssistant.content += data.delta;
        renderBody(state.activeAssistant.body, state.activeAssistant.content, true);
        elements.timeline.scrollTop = elements.timeline.scrollHeight;
      }
    } else if (event.type === "response.completed") {
      if (state.activeAssistant && typeof data.content === "string") {
        state.activeAssistant.content = data.content;
      }
      finishGeneration("");
    } else if (event.type === "response.cancelled") {
      finishGeneration("Generation stopped.");
    } else if (event.type === "error") {
      const message = typeof data.message === "string" ? data.message : "The request could not be completed.";
      if (state.generating) {
        finishGeneration(message, true);
      } else {
        appendMessage("system", message, {error: true});
      }
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
      let event;
      try {
        event = JSON.parse(message.data);
      } catch (_error) {
        appendMessage("system", "Received an unreadable server event.", {error: true});
        return;
      }
      appendTrace("RX", event);
      handleEvent(event);
    });
    socket.addEventListener("close", () => {
      if (state.socket !== socket) {
        return;
      }
      state.socket = null;
      if (state.generating) {
        finishGeneration("Connection closed; the last message was not replayed.", true);
      }
      if (state.intentionalClose) {
        return;
      }
      if (state.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        setStatus("Offline", "error");
        appendMessage("system", "Reconnect limit reached. Start a new session to retry.", {error: true});
        return;
      }
      state.reconnectAttempts += 1;
      const delay = Math.min(8000, 500 * (2 ** (state.reconnectAttempts - 1)));
      setStatus(`Retry ${state.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}`, "connecting");
      state.reconnectTimer = window.setTimeout(connect, delay);
    });
    socket.addEventListener("error", () => setStatus("Link error", "error"));
  }

  function sendEvent(event) {
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN) {
      appendMessage("system", "Connection is not ready.", {error: true});
      return false;
    }
    appendTrace("TX", event);
    state.socket.send(JSON.stringify(event));
    return true;
  }

  function submitMessage() {
    if (state.generating) {
      if (state.activeResponseId) {
        sendEvent({type: "response.cancel", data: {response_id: state.activeResponseId}});
      }
      return;
    }
    const content = elements.input.value.trim();
    if (!content || content.length > MAX_MESSAGE_LENGTH || state.connection !== "ready") {
      return;
    }
    state.messageSequence += 1;
    const messageId = `msg_${randomToken()}_${state.messageSequence}`.slice(0, 128);
    const event = {type: "message.create", data: {message_id: messageId, content}};
    if (sendEvent(event)) {
      appendMessage("user", content);
      elements.input.value = "";
      elements.count.textContent = `0 / ${MAX_MESSAGE_LENGTH}`;
      updateControls();
    }
  }

  elements.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    submitMessage();
  });
  elements.input.addEventListener("input", () => {
    elements.count.textContent = `${elements.input.value.length} / ${MAX_MESSAGE_LENGTH}`;
    updateControls();
  });
  elements.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  });
  elements.newSession.addEventListener("click", () => {
    state.intentionalClose = true;
    clearTimeout(state.reconnectTimer);
    if (state.socket) {
      state.socket.close(1000, "new session");
    }
    state.conversationId = createConversationId();
    state.reconnectAttempts = 0;
    state.generating = false;
    state.activeResponseId = null;
    state.activeAssistant = null;
    elements.conversationId.textContent = state.conversationId;
    while (elements.timeline.firstChild) {
      elements.timeline.removeChild(elements.timeline.firstChild);
    }
    while (elements.trace.firstChild) {
      elements.trace.removeChild(elements.trace.firstChild);
    }
    persistConversationId();
    appendMessage("system", "New local session created.");
    connect();
  });
  elements.clearDisplay.addEventListener("click", () => {
    while (elements.timeline.firstChild) {
      elements.timeline.removeChild(elements.timeline.firstChild);
    }
    while (elements.trace.firstChild) {
      elements.trace.removeChild(elements.trace.firstChild);
    }
    appendMessage("system", "Local display cleared; server conversation state is unchanged.");
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
  appendMessage("system", "Diagnostic channel initialized. Waiting for runtime readiness.");
  updateControls();
  connect();
})();
