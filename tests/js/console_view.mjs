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
    this.clientHeight = 0;
    this._scrollHeight = null;
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
    return this._scrollHeight ?? this.children.length;
  }

  set scrollHeight(value) {
    this._scrollHeight = value;
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
const elements = {timeline: new Node("div"), liveStatus: new Node("p")};
const modulePath = resolve("src/somai_chat/web/view.js");
const {createConsoleView} = await import(`${pathToFileURL(modulePath).href}?view-test=1`);
const view = createConsoleView({
  document,
  window,
  elements,
  limits: {responseCodePoints: 5, timelineMessages: 3},
});

elements.timeline.clientHeight = 100;
elements.timeline.scrollHeight = 200;
elements.timeline.scrollTop = 52;
view.appendMessage("system", "follow-me");
assert(elements.timeline.scrollTop === elements.timeline.scrollHeight, "near-bottom reader did not follow");

elements.timeline.scrollHeight = 400;
elements.timeline.scrollTop = 120;
view.appendMessage("system", "keep-reading");
assert(elements.timeline.scrollTop === 120, "history reader was pulled to the bottom");

for (let index = 0; index < 4; index += 1) {
  view.appendMessage("system", `message-${index}`);
}
assert(elements.timeline.childElementCount === 3, "timeline limit was not enforced");

view.startAssistant({requestStartedAt: 1000});
const assistant = elements.timeline.children.at(-1);
assert(assistant.textContent.includes("First token: --"), "assistant timing metadata was not initialized");
assert(assistant.textContent.includes("Total: 0.00s"), "assistant total timing was not initialized");
view.updateAssistantTiming({now: 1250, firstTokenAt: 1200});
assert(assistant.textContent.includes("First token: 0.20s"), "assistant first token timing was not rendered");
assert(assistant.textContent.includes("Total: 0.25s"), "assistant total timing was not rendered");
view.appendMessage("system", "one");
view.appendMessage("system", "two");
assert(elements.timeline.children.includes(assistant), "active assistant was removed by timeline trimming");
elements.timeline.scrollHeight = 400;
elements.timeline.scrollTop = 120;
view.appendAssistantDelta("abc");
view.appendAssistantDelta("def");
assert(frames.size === 1, "assistant deltas scheduled more than one frame");
const [[pendingId, render]] = frames.entries();
frames.delete(pendingId);
render();
assert(elements.timeline.scrollTop === 120, "streaming output pulled a history reader to the bottom");
assert(assistant.textContent.includes("abcde"), "assistant display did not retain the bounded response");
assert(assistant.textContent.includes("truncated"), "assistant display omitted its truncation marker");

view.appendAssistantDelta("ignored");
assert(frames.size === 0, "truncated response scheduled a redundant render frame");
view.finishAssistant();
assert(frames.size === 0, "terminal rendering did not cancel the pending frame");

view.announce("Response completed.");
assert(elements.liveStatus.textContent === "Response completed.", "live status was not updated");
view.clearDisplay();
assert(elements.timeline.childElementCount === 0, "view clear did not remove timeline messages");

console.log("console view boundary harness passed");
