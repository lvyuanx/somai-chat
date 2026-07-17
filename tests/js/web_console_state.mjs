import {pathToFileURL} from "node:url";
import {resolve} from "node:path";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

class FakeNode {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName;
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.dataset = {};
    this.className = "";
    this.disabled = false;
    this.value = "";
    this.scrollTop = 0;
    this._text = "";
  }

  get textContent() {
    if (this.children.length) {
      return this.children.map((child) => child.textContent).join("");
    }
    return this._text;
  }

  set textContent(value) {
    this.children = [];
    this._text = String(value);
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get firstElementChild() {
    return this.children.find((child) => child.tagName !== "#text") || null;
  }

  get childElementCount() {
    return this.children.filter((child) => child.tagName !== "#text").length;
  }

  get scrollHeight() {
    return this.children.length;
  }

  append(...nodes) {
    this._text = "";
    for (const node of nodes) {
      if (node.tagName === "#fragment") {
        this.children.push(...node.children);
        node.children = [];
      } else {
        this.children.push(node);
      }
    }
  }

  removeChild(node) {
    const index = this.children.indexOf(node);
    if (index >= 0) {
      this.children.splice(index, 1);
    }
    return node;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, event = {}) {
    const payload = {preventDefault() {}, ...event};
    for (const listener of this.listeners.get(type) || []) {
      listener(payload);
    }
  }

  focus() {}
}

class FakeDocument {
  constructor() {
    this.fragmentCount = 0;
    this.elements = new Map();
    for (const id of [
      "composer",
      "message-input",
      "send-stop",
      "message-timeline",
      "event-trace",
      "connection-status",
      "conversation-id",
      "model-name",
      "character-count",
      "new-session",
      "clear-display",
      "composer-hint",
      "live-status",
    ]) {
      this.elements.set(id, new FakeNode("div", this));
    }
  }

  getElementById(id) {
    return this.elements.get(id);
  }

  createElement(tagName) {
    return new FakeNode(tagName, this);
  }

  createTextNode(value) {
    const node = new FakeNode("#text", this);
    node.textContent = value;
    return node;
  }

  createDocumentFragment() {
    this.fragmentCount += 1;
    return new FakeNode("#fragment", this);
  }
}

class FakeWebSocket {
  static OPEN = 1;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.OPEN;
    this.listeners = new Map();
    this.sent = [];
    this.closed = false;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  send(payload) {
    this.sent.push(JSON.parse(payload));
  }

  close() {
    this.closed = true;
  }

  emit(type, data = undefined) {
    const event = type === "message" ? {data: JSON.stringify(data)} : {};
    for (const listener of this.listeners.get(type) || []) {
      listener(event);
    }
  }
}

const document = new FakeDocument();
const stored = new Map();
const windowListeners = new Map();
const rafCallbacks = new Map();
const intervals = new Map();
let rafSequence = 0;
let intervalSequence = 0;
let uuidSequence = 0;
let now = 1000;

const windowObject = {
  location: {protocol: "http:", host: "console.test"},
  localStorage: {
    getItem(key) {
      return stored.get(key) || null;
    },
    setItem(key, value) {
      stored.set(key, value);
    },
  },
  crypto: {
    randomUUID() {
      uuidSequence += 1;
      return `00000000-0000-4000-8000-${String(uuidSequence).padStart(12, "0")}`;
    },
  },
  setTimeout() {
    return 1;
  },
  clearTimeout() {},
  setInterval(callback) {
    intervalSequence += 1;
    intervals.set(intervalSequence, callback);
    return intervalSequence;
  },
  clearInterval(identifier) {
    intervals.delete(identifier);
  },
  requestAnimationFrame(callback) {
    rafSequence += 1;
    rafCallbacks.set(rafSequence, callback);
    return rafSequence;
  },
  cancelAnimationFrame(identifier) {
    rafCallbacks.delete(identifier);
  },
  addEventListener(type, listener) {
    windowListeners.set(type, listener);
  },
};

globalThis.document = document;
globalThis.window = windowObject;
globalThis.WebSocket = FakeWebSocket;
globalThis.requestAnimationFrame = windowObject.requestAnimationFrame;
globalThis.cancelAnimationFrame = windowObject.cancelAnimationFrame;
globalThis.Date.now = () => now;

const appPath = resolve("src/somai_chat/web/app.js");
await import(`${pathToFileURL(appPath).href}?state-test=1`);

const input = document.getElementById("message-input");
const composer = document.getElementById("composer");
const button = document.getElementById("send-stop");
const clear = document.getElementById("clear-display");
const newSession = document.getElementById("new-session");
const timeline = document.getElementById("message-timeline");
const trace = document.getElementById("event-trace");
const model = document.getElementById("model-name");
const status = document.getElementById("connection-status");
const count = document.getElementById("character-count");
const hint = document.getElementById("composer-hint");
const liveStatus = document.getElementById("live-status");

const firstSocket = FakeWebSocket.instances[0];
firstSocket.emit("message", {
  type: "conversation.ready",
  data: {model: "first", max_message_length: 2, max_websocket_message_bytes: 1000},
});
newSession.emit("click");
const socket = FakeWebSocket.instances[1];
socket.emit("message", {
  type: "conversation.ready",
  data: {model: "fallback", max_message_length: -1, max_websocket_message_bytes: 0},
});
assert(count.textContent === "0 / 8000", "invalid ready limits did not use safe defaults");
socket.emit("message", {
  type: "conversation.ready",
  data: {model: "fresh", max_message_length: 2, max_websocket_message_bytes: 1000},
});
const freshStatus = status.textContent;
firstSocket.emit("message", {
  type: "conversation.ready",
  data: {model: "stale", max_message_length: 999, max_websocket_message_bytes: 999},
});
firstSocket.emit("error");
firstSocket.emit("close");
assert(model.textContent === "fresh", "an old socket changed the model");
assert(status.textContent === freshStatus, "an old socket changed connection status");
socket.emit("message", null);
assert(liveStatus.textContent.includes("malformed"), "malformed event error was not announced");

input.value = "😀a";
input.emit("input");
assert(count.textContent === "2 / 2", "message count must use Unicode code points");
assert(hint.textContent.includes("2"), "ready message limit was not shown");
composer.emit("submit");
assert(socket.sent.length === 1, "valid emoji message was not sent once");
assert(button.textContent === "Waiting" && button.disabled, "pending controls are not locked");
assert(input.disabled && clear.disabled, "pending input and clear controls are not locked");
composer.emit("submit");
assert(socket.sent.length === 1, "pending request sent a duplicate message");

const messageId = socket.sent[0].data.message_id;
socket.emit("message", {
  type: "response.started",
  data: {message_id: "msg_wrong", response_id: "resp_wrong"},
});
assert(button.textContent === "Waiting", "mismatched started changed the pending request");
socket.emit("message", {
  type: "response.started",
  data: {message_id: messageId, response_id: "resp_active"},
});
assert(button.textContent === "Stop" && !button.disabled, "matching started did not begin streaming");
assert(clear.disabled, "clear must stay disabled while streaming");
assert(intervals.size === 1, "active response timing did not start a refresh interval");
const timedAssistant = timeline.children.find((node) => node.className.includes("message--assistant"));
assert(timedAssistant.textContent.includes("First token: --"), "response timing was not shown on the active reply");
now = 1234;
socket.emit("message", {
  type: "response.delta",
  data: {response_id: "resp_active", delta: "x"},
});
assert(timedAssistant.textContent.includes("First token: 0.23s"), "first token timing did not use request send time");
assert(timedAssistant.textContent.includes("Total: 0.23s"), "total timing did not update on the active reply");
now = 1750;
for (const refreshTiming of intervals.values()) {
  refreshTiming();
}
assert(timedAssistant.textContent.includes("Total: 0.75s"), "total timing did not refresh without a delta");
const timelineBeforeClear = timeline.childElementCount;
clear.emit("click");
assert(timeline.childElementCount === timelineBeforeClear, "clear removed an active response");

const fragmentsBeforeDeltas = document.fragmentCount;
const liveBeforeDeltas = liveStatus.textContent;
for (let index = 0; index < 100; index += 1) {
  socket.emit("message", {
    type: "response.delta",
    data: {response_id: "resp_active", delta: "x".repeat(2000)},
  });
}
assert(rafCallbacks.size === 1, "delta rendering scheduled more than one frame");
assert(document.fragmentCount === fragmentsBeforeDeltas, "delta rendered before the animation frame");
assert(liveStatus.textContent === liveBeforeDeltas, "delta text was announced through the live region");
const [[frameId, frameCallback]] = rafCallbacks.entries();
rafCallbacks.delete(frameId);
frameCallback();
assert(document.fragmentCount === fragmentsBeforeDeltas + 1, "one frame did not produce exactly one render");
const assistant = timeline.children.find((node) => node.className.includes("message--assistant"));
assert(assistant.textContent.includes("truncated"), "oversized response was not marked as truncated");
assert(Array.from(assistant.textContent).length <= 100100, "oversized response was retained in the DOM");
assert(trace.childElementCount <= 120, "trace event count is unbounded");
for (let index = 0; index < 105; index += 1) {
  socket.emit("message", {type: "error", data: {message: `active-unrelated-${index}`}});
}
assert(timeline.children.includes(assistant), "timeline trimming removed the active assistant");
assert(timeline.childElementCount <= 100, "active timeline message count is unbounded");

composer.emit("submit");
assert(socket.sent.length === 2 && socket.sent[1].type === "response.cancel", "stop was not sent once");
assert(button.textContent === "Stopping" && button.disabled, "cancelling controls are not locked");
const timelineBeforeCancellingClear = timeline.childElementCount;
clear.emit("click");
assert(timeline.childElementCount === timelineBeforeCancellingClear, "clear changed a cancelling response");
composer.emit("submit");
assert(socket.sent.length === 2, "cancelling sent a duplicate stop");
socket.emit("message", {type: "response.completed", data: {response_id: "resp_late", content: "wrong"}});
assert(button.textContent === "Stopping", "mismatched completed ended the active request");
socket.emit("message", {type: "response.cancelled", data: {response_id: "resp_active"}});
assert(!input.disabled && !clear.disabled, "terminal event did not restore idle controls");
assert(intervals.size === 0, "terminal event did not stop the timing refresh interval");
assert(liveStatus.textContent.includes("stopped"), "terminal status was not announced");

input.value = "b";
input.emit("input");
composer.emit("submit");
const secondMessage = socket.sent.at(-1);
socket.emit("message", {
  type: "response.started",
  data: {message_id: secondMessage.data.message_id, response_id: "resp_second"},
});
socket.emit("message", {type: "response.delta", data: {response_id: "resp_second", delta: "draft"}});
assert(rafCallbacks.size === 1, "second response did not schedule its delta frame");
socket.emit("message", {type: "response.completed", data: {response_id: "resp_second", content: "final"}});
assert(rafCallbacks.size === 0, "completed did not cancel the pending render frame");
assert(timeline.textContent.includes("final"), "completed did not synchronously flush final content");
assert(liveStatus.textContent.includes("completed"), "completed status was not announced");

clear.emit("click");
assert(timeline.childElementCount === 1, "idle clear did not reset the local timeline");
socket.emit("message", {
  type: "conversation.ready",
  data: {model: "fresh", max_message_length: 1, max_websocket_message_bytes: 1000},
});
const sentBeforeCodePointLimit = socket.sent.length;
input.value = "😀a";
input.emit("input");
composer.emit("submit");
assert(socket.sent.length === sentBeforeCodePointLimit, "message beyond the code point limit was sent");
assert(liveStatus.textContent.includes("code point limit"), "message code point error was not announced");
socket.emit("message", {
  type: "conversation.ready",
  data: {model: "fresh", max_message_length: 100, max_websocket_message_bytes: 30},
});
const sentBeforeOversize = socket.sent.length;
input.value = "ok";
input.emit("input");
composer.emit("submit");
assert(socket.sent.length === sentBeforeOversize, "oversized WebSocket frame was sent");
assert(!input.disabled, "local frame rejection left the composer pending");
assert(liveStatus.textContent.includes("limit"), "local limit error was not announced");

for (let index = 0; index < 110; index += 1) {
  socket.emit("message", {type: "error", data: {message: `unrelated-${index}`}});
}
assert(timeline.childElementCount <= 100, "timeline message count is unbounded");
socket.emit("message", {type: "unknown", data: {content: "z".repeat(20000)}});
const tracePayload = trace.children.at(-1).children[1].textContent;
assert(tracePayload.includes("truncated"), "large trace event was not marked as truncated");
assert(Array.from(tracePayload).length <= 12100, "large trace event was retained without a display bound");

console.log("web console state harness passed");
