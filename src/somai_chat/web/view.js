import {markdownNodes} from "./markdown.js";

const FOLLOW_THRESHOLD_PX = 48;

export function codePointLength(value) {
  return Array.from(value).length;
}

function shouldFollowTimeline(timeline) {
  return timeline.scrollHeight - timeline.clientHeight - timeline.scrollTop <= FOLLOW_THRESHOLD_PX;
}

function boundedText(value, limit) {
  const points = [];
  let truncated = false;
  for (const point of value) {
    if (points.length >= limit) {
      truncated = true;
      break;
    }
    points.push(point);
  }
  return {text: points.join(""), count: points.length, truncated};
}

export function createConsoleView({document, window, elements, limits}) {
  const responseNotice = "\n\n[Response truncated at the local display limit.]";
  const traceNotice = "\n… [trace truncated]";
  let activeAssistant = null;
  let renderFrameId = null;

  function renderBody(body, content, streaming) {
    while (body.firstChild) {
      body.removeChild(body.firstChild);
    }
    body.append(markdownNodes(content, document));
    if (streaming) {
      const cursor = document.createElement("span");
      cursor.className = "streaming-cursor";
      cursor.setAttribute("aria-label", "Response streaming");
      body.append(cursor);
    }
  }

  function trimTimeline(protectedArticle) {
    while (elements.timeline.childElementCount > limits.timelineMessages) {
      const activeArticle = activeAssistant ? activeAssistant.article : null;
      const removable = Array.from(elements.timeline.children).find(
        (node) => node !== activeArticle && node !== protectedArticle,
      );
      if (!removable) {
        return;
      }
      elements.timeline.removeChild(removable);
    }
  }

  function appendMessage(role, content, options = {}) {
    const shouldFollow = shouldFollowTimeline(elements.timeline);
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
    trimTimeline(article);
    if (shouldFollow) {
      elements.timeline.scrollTop = elements.timeline.scrollHeight;
    }
    return {article, body, content, codePointCount: codePointLength(content), truncated: false};
  }

  function appendTrace(direction, event) {
    const item = document.createElement("li");
    const directionNode = document.createElement("span");
    const payload = document.createElement("pre");
    item.className = "trace-event";
    directionNode.className = "trace-event__direction";
    directionNode.textContent = direction;
    payload.className = "trace-event__payload";
    const bounded = boundedText(JSON.stringify(event, null, 2), limits.traceCodePoints);
    payload.textContent = bounded.text + (bounded.truncated ? traceNotice : "");
    item.append(directionNode, payload);
    elements.trace.append(item);
    while (elements.trace.childElementCount > limits.traceEvents) {
      elements.trace.removeChild(elements.trace.firstElementChild);
    }
    elements.trace.scrollTop = elements.trace.scrollHeight;
  }

  function displayContent() {
    if (!activeAssistant) {
      return "";
    }
    return activeAssistant.content + (activeAssistant.truncated ? responseNotice : "");
  }

  function renderAssistant(streaming) {
    if (!activeAssistant) {
      return;
    }
    const shouldFollow = shouldFollowTimeline(elements.timeline);
    renderBody(activeAssistant.body, displayContent(), streaming);
    if (shouldFollow) {
      elements.timeline.scrollTop = elements.timeline.scrollHeight;
    }
  }

  function cancelScheduledRender() {
    if (renderFrameId !== null) {
      window.cancelAnimationFrame(renderFrameId);
      renderFrameId = null;
    }
  }

  function scheduleRender() {
    if (renderFrameId !== null) {
      return;
    }
    renderFrameId = window.requestAnimationFrame(() => {
      renderFrameId = null;
      renderAssistant(true);
    });
  }

  function startAssistant() {
    activeAssistant = appendMessage("assistant", "", {streaming: true});
  }

  function appendAssistantDelta(delta) {
    if (!activeAssistant || activeAssistant.truncated) {
      return;
    }
    const remaining = limits.responseCodePoints - activeAssistant.codePointCount;
    const bounded = boundedText(delta, remaining);
    activeAssistant.content += bounded.text;
    activeAssistant.codePointCount += bounded.count;
    activeAssistant.truncated = bounded.truncated;
    scheduleRender();
  }

  function replaceAssistantContent(content) {
    if (!activeAssistant) {
      return;
    }
    const bounded = boundedText(content, limits.responseCodePoints);
    activeAssistant.content = bounded.text;
    activeAssistant.codePointCount = bounded.count;
    activeAssistant.truncated = bounded.truncated;
  }

  function finishAssistant() {
    cancelScheduledRender();
    renderAssistant(false);
    activeAssistant = null;
  }

  function discardAssistant() {
    cancelScheduledRender();
    activeAssistant = null;
  }

  function announce(message) {
    elements.liveStatus.textContent = message;
  }

  function clearDisplay() {
    while (elements.timeline.firstChild) {
      elements.timeline.removeChild(elements.timeline.firstChild);
    }
    while (elements.trace.firstChild) {
      elements.trace.removeChild(elements.trace.firstChild);
    }
  }

  return {
    announce,
    appendAssistantDelta,
    appendMessage,
    appendTrace,
    clearDisplay,
    discardAssistant,
    finishAssistant,
    replaceAssistantContent,
    startAssistant,
  };
}
