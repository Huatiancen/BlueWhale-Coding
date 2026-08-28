const INLINE_PATTERNS = [
  { type: "code", expression: /`([^`\n]+)`/ },
  { type: "link", expression: /\[([^\]\n]+)\]\(([^\s)]+)\)/ },
  { type: "strong", expression: /\*\*([^*\n]+)\*\*/ },
  { type: "delete", expression: /~~([^~\n]+)~~/ },
  { type: "emphasis", expression: /(?:\*([^*\n]+)\*|_([^_\n]+)_)/ },
];

export function renderMarkdown(source, documentRef = document) {
  const root = documentRef.createElement("div");
  root.className = "markdown-body";
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```([^`]*)$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const pre = documentRef.createElement("pre");
      const code = documentRef.createElement("code");
      const language = fence[1].trim().replace(/[^A-Za-z0-9_-]/g, "");
      if (language) code.className = `language-${language}`;
      code.textContent = codeLines.join("\n");
      pre.append(code);
      root.append(pre);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const node = documentRef.createElement(`h${heading[1].length}`);
      renderInline(node, heading[2], documentRef);
      root.append(node);
      index += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      const quote = documentRef.createElement("blockquote");
      const paragraph = documentRef.createElement("p");
      renderInline(paragraph, quoteLines.join(" "), documentRef);
      quote.append(paragraph);
      root.append(quote);
      continue;
    }

    const listMatch = line.match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
    if (listMatch) {
      const ordered = Boolean(listMatch[2]);
      const list = documentRef.createElement(ordered ? "ol" : "ul");
      while (index < lines.length) {
        const itemMatch = lines[index].match(/^\s*(?:([-+*])|(\d+)\.)\s+(.+)$/);
        if (!itemMatch || Boolean(itemMatch[2]) !== ordered) break;
        const item = documentRef.createElement("li");
        renderInline(item, itemMatch[3], documentRef);
        list.append(item);
        index += 1;
      }
      root.append(list);
      continue;
    }

    if (/^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)) {
      root.append(documentRef.createElement("hr"));
      index += 1;
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    const paragraph = documentRef.createElement("p");
    renderInline(paragraph, paragraphLines.join(" "), documentRef);
    root.append(paragraph);
  }

  return root;
}

export function isSafeLink(value) {
  const link = String(value || "").trim();
  if (!link || link.startsWith("//") || link.startsWith("\\")) return false;
  try {
    const parsed = new URL(link, "https://bluewhale.invalid/");
    return ["http:", "https:", "mailto:"].includes(parsed.protocol);
  } catch (_error) {
    return false;
  }
}

function startsBlock(line) {
  return (
    /^\s*```/.test(line) ||
    /^(?:#{1,6})\s+/.test(line) ||
    /^\s*>\s?/.test(line) ||
    /^\s*(?:[-+*]|\d+\.)\s+/.test(line) ||
    /^\s*(?:---+|___+|\*\*\*+)\s*$/.test(line)
  );
}

function renderInline(parent, source, documentRef) {
  let remaining = source;
  while (remaining) {
    const match = earliestInlineMatch(remaining);
    if (!match) {
      parent.append(documentRef.createTextNode(remaining));
      break;
    }
    if (match.index > 0) {
      parent.append(documentRef.createTextNode(remaining.slice(0, match.index)));
    }
    appendInlineToken(parent, match, documentRef);
    remaining = remaining.slice(match.index + match.value.length);
  }
}

function earliestInlineMatch(source) {
  let earliest = null;
  for (const pattern of INLINE_PATTERNS) {
    const found = pattern.expression.exec(source);
    if (!found || (earliest && found.index >= earliest.index)) continue;
    earliest = { type: pattern.type, index: found.index, value: found[0], groups: found };
  }
  return earliest;
}

function appendInlineToken(parent, token, documentRef) {
  if (token.type === "link") {
    const [, label, href] = token.groups;
    if (!isSafeLink(href)) {
      parent.append(documentRef.createTextNode(label));
      return;
    }
    const anchor = documentRef.createElement("a");
    anchor.setAttribute("href", href);
    if (/^https?:/i.test(href)) {
      anchor.setAttribute("target", "_blank");
      anchor.setAttribute("rel", "noreferrer noopener");
    }
    renderInline(anchor, label, documentRef);
    parent.append(anchor);
    return;
  }

  const tagNames = { code: "code", strong: "strong", delete: "del", emphasis: "em" };
  const node = documentRef.createElement(tagNames[token.type]);
  const content = token.type === "emphasis" ? token.groups[1] || token.groups[2] : token.groups[1];
  if (token.type === "code") node.textContent = content;
  else renderInline(node, content, documentRef);
  parent.append(node);
}
