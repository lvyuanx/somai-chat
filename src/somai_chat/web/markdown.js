function appendInline(parent, source, documentRef) {
  const tokenPattern = /(`[^`\n]+`|\[[^\]\n]+\]\([^\s)]+\))/g;
  let cursor = 0;
  for (const match of source.matchAll(tokenPattern)) {
    const index = match.index || 0;
    parent.append(documentRef.createTextNode(source.slice(cursor, index)));
    const token = match[0];
    if (token.startsWith("`")) {
      const code = documentRef.createElement("code");
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
        const link = documentRef.createElement("a");
        link.textContent = label;
        link.setAttribute("href", safeUrl);
        link.setAttribute("target", "_blank");
        link.setAttribute("rel", "noopener noreferrer");
        parent.append(link);
      } else {
        parent.append(documentRef.createTextNode(label));
      }
    }
    cursor = index + token.length;
  }
  parent.append(documentRef.createTextNode(source.slice(cursor)));
}

export function markdownNodes(source, documentRef = document) {
  const fragment = documentRef.createDocumentFragment();
  const lines = source.replaceAll("\r\n", "\n").split("\n");
  let lineIndex = 0;
  let paragraph = [];

  function flushParagraph() {
    if (!paragraph.length) {
      return;
    }
    const node = documentRef.createElement("p");
    appendInline(node, paragraph.join(" "), documentRef);
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
      const pre = documentRef.createElement("pre");
      const code = documentRef.createElement("code");
      code.textContent = codeLines.join("\n");
      pre.append(code);
      fragment.append(pre);
    } else {
      const heading = /^(#{1,3})\s+(.+)$/.exec(line);
      const listItem = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(line);
      if (heading) {
        flushParagraph();
        const node = documentRef.createElement(`h${heading[1].length}`);
        appendInline(node, heading[2], documentRef);
        fragment.append(node);
      } else if (listItem) {
        flushParagraph();
        const ordered = listItem[2].endsWith(".");
        const list = documentRef.createElement(ordered ? "ol" : "ul");
        while (lineIndex < lines.length) {
          const item = /^(\s*)([-*]|\d+\.)\s+(.+)$/.exec(lines[lineIndex]);
          if (!item || item[2].endsWith(".") !== ordered) {
            break;
          }
          const listNode = documentRef.createElement("li");
          appendInline(listNode, item[3], documentRef);
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
