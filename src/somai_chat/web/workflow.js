const TOOL_LABELS = {
  get_current_time: "时间工具",
  get_weather: "天气工具",
  web_search: "联网搜索",
  camera_capture: "摄像头工具",
};

const STATUS_LABELS = {
  running: "运行中",
  completed: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
  interrupted: "连接中断",
};

function nodeLabel(node) {
  if (node.kind === "model") return "大模型";
  return TOOL_LABELS[node.name] || node.name || "工具";
}

function formatDuration(milliseconds) {
  return `${(Math.max(0, milliseconds) / 1000).toFixed(2)}s`;
}

function formatPayload(value) {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return "[无法显示内容]";
  }
}

function makePayload(document, label, value, truncated) {
  const section = document.createElement("div");
  const heading = document.createElement("span");
  const payload = document.createElement("pre");
  section.className = "workflow-node__payload";
  heading.className = "workflow-node__payload-label";
  heading.textContent = truncated ? `${label} · 已截断` : label;
  payload.textContent = formatPayload(value);
  section.append(heading, payload);
  return section;
}

export function createWorkflowView({document, window, elements, limits, now = () => Date.now()}) {
  const state = {
    responseId: null,
    nodes: [],
    startedAt: null,
    finishedElapsedMs: null,
    terminal: null,
    truncated: false,
    timer: null,
    drawerOpen: false,
    previousFocus: null,
  };

  function stopTimer() {
    if (state.timer !== null) {
      window.clearInterval(state.timer);
      state.timer = null;
    }
  }

  function elapsed() {
    if (state.finishedElapsedMs !== null) return state.finishedElapsedMs;
    return state.startedAt === null ? 0 : now() - state.startedAt;
  }

  function updateSummary() {
    const current = [...state.nodes].reverse().find((node) => node.status === "running") || state.nodes.at(-1);
    elements.summaryName.textContent = current ? nodeLabel(current) : "工作流准备中";
    const status = state.terminal ? STATUS_LABELS[state.terminal] : current ? STATUS_LABELS[current.status] : "等待节点";
    elements.summaryMeta.textContent = `${status} · ${state.nodes.length} 个节点 · ${formatDuration(elapsed())}`;
    elements.sheetStatus.textContent = state.terminal ? STATUS_LABELS[state.terminal] : `LIVE · ${formatDuration(elapsed())}`;
  }

  function toggleNode(nodeId) {
    const node = state.nodes.find((item) => item.id === nodeId);
    if (!node || node.kind !== "tool") return;
    node.expanded = !node.expanded;
    render();
  }

  function renderNode(node) {
    const item = document.createElement("li");
    const header = document.createElement("button");
    const identity = document.createElement("span");
    const name = document.createElement("strong");
    const status = document.createElement("span");
    const duration = document.createElement("span");
    const detail = document.createElement("div");
    const hasDetail = node.kind === "tool" && (node.input !== undefined || node.output !== undefined);

    item.className = "workflow-node";
    item.dataset.status = node.status;
    header.className = "workflow-node__header";
    header.type = "button";
    header.disabled = !hasDetail;
    header.setAttribute("aria-expanded", String(Boolean(node.expanded && hasDetail)));
    identity.className = "workflow-node__identity";
    name.textContent = nodeLabel(node);
    status.className = "workflow-node__status";
    status.textContent = STATUS_LABELS[node.status];
    identity.append(name, status);
    duration.className = "workflow-node__duration";
    duration.textContent = node.durationMs === null ? "LIVE" : formatDuration(node.durationMs);
    header.append(identity, duration);
    if (hasDetail) header.addEventListener("click", () => toggleNode(node.id));

    detail.className = "workflow-node__details";
    detail.hidden = !node.expanded || !hasDetail;
    if (node.input !== undefined) {
      detail.append(makePayload(document, "INPUT", node.input, node.inputTruncated));
    }
    if (node.output !== undefined) {
      detail.append(makePayload(document, "OUTPUT", node.output, node.outputTruncated));
    }
    item.append(header, detail);
    return item;
  }

  function renderList(list) {
    const children = state.nodes.map(renderNode);
    if (state.truncated) {
      const notice = document.createElement("li");
      notice.className = "workflow-truncated";
      notice.textContent = "更多节点已省略";
      children.push(notice);
    }
    list.replaceChildren(...children);
  }

  function render() {
    renderList(elements.desktopList);
    renderList(elements.mobileList);
    elements.desktopEmpty.hidden = state.nodes.length > 0;
    updateSummary();
  }

  function closeDrawer() {
    if (!state.drawerOpen) return;
    state.drawerOpen = false;
    elements.sheet.hidden = true;
    elements.backdrop.hidden = true;
    elements.summary.setAttribute("aria-expanded", "false");
    if (state.previousFocus && typeof state.previousFocus.focus === "function") {
      state.previousFocus.focus();
    }
    state.previousFocus = null;
  }

  function openDrawer() {
    if (elements.summary.hidden || state.drawerOpen) return;
    state.drawerOpen = true;
    state.previousFocus = document.activeElement;
    elements.sheet.hidden = false;
    elements.backdrop.hidden = false;
    elements.summary.setAttribute("aria-expanded", "true");
    elements.close.focus();
  }

  function clear() {
    stopTimer();
    closeDrawer();
    state.responseId = null;
    state.nodes = [];
    state.startedAt = null;
    state.finishedElapsedMs = null;
    state.terminal = null;
    state.truncated = false;
    elements.summary.hidden = true;
    render();
  }

  function start(responseId, requestStartedAt = now()) {
    clear();
    state.responseId = responseId;
    state.startedAt = requestStartedAt;
    elements.summary.hidden = false;
    state.timer = window.setInterval(updateSummary, 100);
    render();
  }

  function handle(event) {
    const data = event && typeof event.data === "object" ? event.data : {};
    if (!state.responseId || data.response_id !== state.responseId) return false;
    if (event.type === "workflow.node.started") {
      if (state.nodes.some((node) => node.id === data.node_id)) return false;
      if (state.nodes.length >= limits.nodes) {
        state.truncated = true;
        render();
        return true;
      }
      const kind = data.kind === "tool" ? "tool" : "model";
      state.nodes.push({
        id: data.node_id,
        kind,
        name: typeof data.name === "string" ? data.name : kind,
        status: "running",
        durationMs: null,
        input: kind === "tool" ? data.input : undefined,
        inputTruncated: data.input_truncated === true,
        output: undefined,
        outputTruncated: false,
        expanded: kind === "tool",
      });
    } else if (event.type === "workflow.node.completed" || event.type === "workflow.node.failed") {
      const node = state.nodes.find((item) => item.id === data.node_id);
      if (!node) return false;
      node.status = event.type === "workflow.node.failed" ? "failed" : "completed";
      node.durationMs = Number.isFinite(data.duration_ms) ? Math.max(0, data.duration_ms) : 0;
      if (event.type === "workflow.node.completed" && node.kind === "tool") {
        node.output = data.output;
        node.outputTruncated = data.output_truncated === true;
      }
      node.expanded = false;
    } else {
      return false;
    }
    render();
    return true;
  }

  function finish(responseId, terminal) {
    if (responseId !== state.responseId) return;
    const replacement = terminal === "error" ? "failed" : terminal;
    state.finishedElapsedMs = elapsed();
    for (const node of state.nodes) {
      if (node.status === "running") {
        node.status = replacement === "completed" ? "completed" : replacement;
        node.durationMs = state.finishedElapsedMs;
        node.expanded = false;
      }
    }
    state.terminal = replacement;
    stopTimer();
    render();
  }

  elements.summary.setAttribute("aria-expanded", "false");
  elements.summary.addEventListener("click", openDrawer);
  elements.close.addEventListener("click", closeDrawer);
  elements.backdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (!state.drawerOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(elements.sheet.querySelectorAll("button:not([disabled])"));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  render();

  return {clear, closeDrawer, finish, handle, openDrawer, start};
}
