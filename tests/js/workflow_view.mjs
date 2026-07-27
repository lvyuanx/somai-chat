import assert from "node:assert/strict";

import {createWorkflowView} from "../../src/somai_chat/web/workflow.js";

class ClassList {
  constructor(node) {
    this.node = node;
  }
  add(...names) {
    const values = new Set(this.node.className.split(/\s+/).filter(Boolean));
    names.forEach((name) => values.add(name));
    this.node.className = [...values].join(" ");
  }
  remove(...names) {
    const removed = new Set(names);
    this.node.className = this.node.className.split(/\s+/).filter((name) => name && !removed.has(name)).join(" ");
  }
}

class Node {
  constructor(document, tagName = "div") {
    this.ownerDocument = document;
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.dataset = {};
    this.attributes = new Map();
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this._text = "";
    this.listeners = new Map();
    this.classList = new ClassList(this);
  }
  get childElementCount() {
    return this.children.length;
  }
  get firstChild() {
    return this.children[0] ?? null;
  }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) {
    this._text = String(value);
    this.children = [];
  }
  append(...nodes) {
    for (const node of nodes) {
      node.parentNode = this;
      this.children.push(node);
    }
  }
  replaceChildren(...nodes) {
    this.children = [];
    this._text = "";
    this.append(...nodes);
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
  dispatchEvent(event) {
    event.target ??= this;
    event.preventDefault ??= () => {};
    for (const listener of this.listeners.get(event.type) ?? []) listener(event);
  }
  click() {
    this.dispatchEvent({type: "click"});
  }
  focus() {
    this.ownerDocument.activeElement = this;
  }
  querySelectorAll(selector) {
    if (!selector.startsWith("button")) return [];
    const found = [];
    const visit = (node) => {
      if (node.tagName === "BUTTON" && !node.disabled && !node.hidden) found.push(node);
      node.children.forEach(visit);
    };
    visit(this);
    return found;
  }
}

class Document {
  constructor() {
    this.activeElement = null;
    this.listeners = new Map();
  }
  createElement(tagName) {
    return new Node(this, tagName);
  }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
  dispatch(type, event = {}) {
    event.type = type;
    event.preventDefault ??= () => {};
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function fixture(nodeLimit = 120) {
  const document = new Document();
  const make = (tag = "div") => document.createElement(tag);
  const elements = {
    desktopList: make("ol"),
    desktopEmpty: make("p"),
    mobileList: make("ol"),
    summary: make("button"),
    summaryName: make("span"),
    summaryMeta: make("span"),
    sheet: make("section"),
    backdrop: make("div"),
    close: make("button"),
    sheetStatus: make("span"),
  };
  elements.sheet.append(elements.close, elements.mobileList);
  elements.summary.hidden = true;
  elements.sheet.hidden = true;
  elements.backdrop.hidden = true;
  const intervals = new Map();
  let intervalId = 0;
  let currentNow = 2_000;
  const window = {
    setInterval(callback) {
      intervalId += 1;
      intervals.set(intervalId, callback);
      return intervalId;
    },
    clearInterval(id) {
      intervals.delete(id);
    },
  };
  const view = createWorkflowView({document, window, elements, limits: {nodes: nodeLimit}, now: () => currentNow});
  return {document, elements, intervals, setNow: (value) => { currentNow = value; }, view};
}

function event(type, data) {
  return {type, data};
}

{
  const {elements, setNow, view} = fixture();
  view.start("resp-1", 1_000);
  view.handle(event("workflow.node.started", {
    response_id: "resp-1", node_id: "model-1", kind: "model", name: "model",
  }));
  view.handle(event("workflow.node.started", {
    response_id: "resp-1", node_id: "tool-1", kind: "tool", name: "get_weather",
    input: {city: "武汉"}, input_truncated: false,
  }));

  assert.equal(elements.desktopList.childElementCount, 2);
  assert.equal(elements.mobileList.childElementCount, 2);
  assert.match(elements.desktopList.textContent, /大模型/);
  assert.match(elements.desktopList.textContent, /天气工具/);
  assert.equal(elements.summary.hidden, false);
  assert.equal(elements.summaryName.textContent, "天气工具");
  assert.match(elements.desktopList.children[1].textContent, /武汉/);
  assert.equal(elements.desktopList.children[1].dataset.status, "running");

  view.handle(event("workflow.node.completed", {
    response_id: "resp-1", node_id: "tool-1", duration_ms: 321,
    output: {condition: "晴"}, output_truncated: false,
  }));
  assert.equal(elements.desktopList.children[1].dataset.status, "completed");
  assert.equal(elements.desktopList.children[1].children[0].getAttribute("aria-expanded"), "false");
  assert.match(elements.desktopList.children[1].textContent, /0.32s/);

  view.finish("resp-1", "completed");
  const finishedSummary = elements.summaryMeta.textContent;
  setNow(8_000);
  elements.desktopList.children[1].children[0].click();
  assert.equal(elements.summaryMeta.textContent, finishedSummary, "terminal workflow duration was not frozen");

  view.start("resp-2", 2_000);
  assert.equal(elements.desktopList.childElementCount, 0);
  assert.equal(elements.mobileList.childElementCount, 0);
  assert.doesNotMatch(elements.desktopList.textContent, /天气工具/);
}

{
  const {elements, view} = fixture(2);
  view.start("resp-limit", 1_000);
  for (let index = 0; index < 3; index += 1) {
    view.handle(event("workflow.node.started", {
      response_id: "resp-limit", node_id: `node-${index}`, kind: "tool", name: "web_search", input: {},
    }));
  }
  assert.equal(elements.desktopList.childElementCount, 3);
  assert.match(elements.desktopList.children[2].textContent, /更多节点已省略/);
}

{
  const {document, elements, intervals, view} = fixture();
  view.start("resp-cancel", 1_000);
  view.handle(event("workflow.node.started", {
    response_id: "resp-cancel", node_id: "tool-running", kind: "tool", name: "get_current_time", input: {},
  }));
  assert.equal(intervals.size, 1);
  view.finish("resp-cancel", "cancelled");
  assert.equal(elements.desktopList.children[0].dataset.status, "cancelled");
  assert.equal(intervals.size, 0);

  elements.summary.focus();
  elements.summary.click();
  assert.equal(elements.sheet.hidden, false);
  assert.equal(elements.backdrop.hidden, false);
  assert.equal(elements.summary.getAttribute("aria-expanded"), "true");
  assert.equal(document.activeElement, elements.close);
  document.dispatch("keydown", {key: "Escape"});
  assert.equal(elements.sheet.hidden, true);
  assert.equal(elements.summary.getAttribute("aria-expanded"), "false");
  assert.equal(document.activeElement, elements.summary);
}

console.log("workflow view harness passed");
