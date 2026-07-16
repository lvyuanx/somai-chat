import {pathToFileURL} from "node:url";
import {resolve} from "node:path";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

class Node {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = "";
    this._text = "";
    this.attributes = new Map();
    this.scrollTop = 0;
  }

  get textContent() {
    return this.children.length ? this.children.map((child) => child.textContent).join("") : this._text;
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
      } else {
        this.children.push(node);
      }
    }
  }

  removeChild(node) {
    this.children.splice(this.children.indexOf(node), 1);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
}

const document = {
  createElement(tagName) {
    return new Node(tagName);
  },
  createTextNode(value) {
    const node = new Node("#text");
    node.textContent = value;
    return node;
  },
  createDocumentFragment() {
    return new Node("#fragment");
  },
};

const frames = new Map();
let frameId = 0;
const window = {
  requestAnimationFrame(callback) {
    frameId += 1;
    frames.set(frameId, callback);
    return frameId;
  },
  cancelAnimationFrame(identifier) {
    frames.delete(identifier);
  },
};
const elements = {timeline: new Node("div"), trace: new Node("ol"), liveStatus: new Node("p")};
const modulePath = resolve("src/somai_chat/web/view.js");
const {createConsoleView} = await import(`${pathToFileURL(modulePath).href}?view-test=1`);
const view = createConsoleView({
  document,
  window,
  elements,
  limits: {responseCodePoints: 5, timelineMessages: 3, traceEvents: 2, traceCodePoints: 20},
});

for (let index = 0; index < 4; index += 1) {
  view.appendMessage("system", `message-${index}`);
}
assert(elements.timeline.childElementCount === 3, "timeline limit was not enforced");

view.startAssistant();
const assistant = elements.timeline.children.at(-1);
view.appendMessage("system", "one");
view.appendMessage("system", "two");
assert(elements.timeline.children.includes(assistant), "active assistant was removed by timeline trimming");
view.appendAssistantDelta("abc");
view.appendAssistantDelta("def");
assert(frames.size === 1, "assistant deltas scheduled more than one frame");
const [[pendingId, render]] = frames.entries();
frames.delete(pendingId);
render();
assert(assistant.textContent.includes("abcde"), "assistant display did not retain the bounded response");
assert(assistant.textContent.includes("truncated"), "assistant display omitted its truncation marker");

view.appendAssistantDelta("ignored");
assert(frames.size === 0, "truncated response scheduled a redundant render frame");
view.finishAssistant();
assert(frames.size === 0, "terminal rendering did not cancel the pending frame");

view.appendTrace("RX", {content: "x".repeat(100)});
view.appendTrace("RX", {content: "y".repeat(100)});
view.appendTrace("RX", {content: "z".repeat(100)});
assert(elements.trace.childElementCount === 2, "trace event limit was not enforced");
assert(elements.trace.children.at(-1).textContent.includes("truncated"), "trace truncation was not marked");

view.announce("Response completed.");
assert(elements.liveStatus.textContent === "Response completed.", "live status was not updated");
view.clearDisplay();
assert(elements.timeline.childElementCount === 0, "view clear did not remove timeline messages");
assert(elements.trace.childElementCount === 0, "view clear did not remove trace events");

console.log("console view boundary harness passed");
