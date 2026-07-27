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

function formatDuration(milliseconds) {
  return `${(Math.max(0, milliseconds) / 1000).toFixed(2)}s`;
}

export function createConsoleView({document, window, elements, limits}) {
  const responseNotice = "\n\n[Response truncated at the local display limit.]";
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
    if (typeof options.imageSource === "string") {
      const image = document.createElement("img");
      image.className = "message__image";
      image.src = options.imageSource;
      image.alt = "Uploaded image";
      body.append(image);
    }
    article.append(meta, body);
    elements.timeline.append(article);
    trimTimeline(article);
    if (shouldFollow) {
      elements.timeline.scrollTop = elements.timeline.scrollHeight;
    }
    return {article, body, content, codePointCount: codePointLength(content), truncated: false};
  }

  function createAssistantTiming() {
    const timing = document.createElement("div");
    timing.className = "message__timing";
    timing.setAttribute("aria-label", "Response timing");
    return timing;
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

  function startAssistant({requestStartedAt} = {}) {
    activeAssistant = appendMessage("assistant", "", {streaming: true});
    activeAssistant.requestStartedAt = Number.isFinite(requestStartedAt) ? requestStartedAt : 0;
    activeAssistant.firstTokenAt = null;
    activeAssistant.timing = createAssistantTiming();
    activeAssistant.article.append(activeAssistant.timing);
    updateAssistantTiming({now: activeAssistant.requestStartedAt});
  }

  function updateAssistantTiming({now, firstTokenAt} = {}) {
    if (!activeAssistant) {
      return;
    }
    if (Number.isFinite(firstTokenAt) && activeAssistant.firstTokenAt === null) {
      activeAssistant.firstTokenAt = firstTokenAt;
    }
    const currentTime = Number.isFinite(now) ? now : activeAssistant.requestStartedAt;
    const total = formatDuration(currentTime - activeAssistant.requestStartedAt);
    const firstToken = activeAssistant.firstTokenAt === null
      ? "--"
      : formatDuration(activeAssistant.firstTokenAt - activeAssistant.requestStartedAt);
    activeAssistant.timing.textContent = `First token: ${firstToken} | Total: ${total}`;
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
  }

  return {
    announce,
    appendAssistantDelta,
    appendMessage,
    clearDisplay,
    discardAssistant,
    finishAssistant,
    replaceAssistantContent,
    startAssistant,
    updateAssistantTiming,
  };
}
