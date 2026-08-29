export function parseUnifiedDiff(source, totalNewLines = null) {
  const lines = String(source || "").split(/\r?\n/);
  if (lines.at(-1) === "") lines.pop();
  const rows = [];
  let oldLine = null;
  let newLine = null;

  for (const raw of lines) {
    const hunk = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      const oldStart = Number(hunk[1]);
      const newStart = Number(hunk[2]);
      const omitted =
        oldLine === null || newLine === null
          ? Math.max(oldStart - 1, newStart - 1)
          : Math.max(oldStart - oldLine, newStart - newLine);
      if (omitted > 0) rows.push(collapsedRow(omitted));
      oldLine = oldStart;
      newLine = newStart;
      rows.push(row("hunk", null, null, "", raw));
      continue;
    }
    if (raw.startsWith("--- ") || raw.startsWith("+++ ") || raw.startsWith("diff --git ")) {
      rows.push(row("file", null, null, "", raw));
      continue;
    }
    if (oldLine !== null && newLine !== null && raw.startsWith("+")) {
      rows.push(row("addition", null, newLine, "+", raw.slice(1)));
      newLine += 1;
      continue;
    }
    if (oldLine !== null && newLine !== null && raw.startsWith("-")) {
      rows.push(row("deletion", oldLine, null, "-", raw.slice(1)));
      oldLine += 1;
      continue;
    }
    if (oldLine !== null && newLine !== null && raw.startsWith(" ")) {
      rows.push(row("context", oldLine, newLine, " ", raw.slice(1)));
      oldLine += 1;
      newLine += 1;
      continue;
    }
    rows.push(row("meta", null, null, "", raw));
  }
  if (
    Number.isInteger(totalNewLines) &&
    newLine !== null &&
    totalNewLines >= newLine
  ) {
    rows.push(collapsedRow(totalNewLines - newLine + 1));
  }
  return rows;
}

export function renderUnifiedDiff(
  source,
  { documentRef = document, path = "", content = "" } = {},
) {
  const root = documentRef.createElement("div");
  root.className = "artifact-diff";
  root.setAttribute("role", "table");
  root.setAttribute("aria-label", "文件差异");
  root.dataset.path = path;
  for (const parsed of parseUnifiedDiff(source, lineCount(content))) {
    if (parsed.type === "file" || parsed.type === "hunk") continue;
    const line = documentRef.createElement("div");
    line.className = `diff-line ${parsed.type}`;
    line.setAttribute("role", "row");
    if (parsed.type === "collapsed") {
      line.append(cell(documentRef, "diff-collapsed-label", parsed.content));
    } else if (parsed.type === "meta") {
      line.append(cell(documentRef, "diff-code", parsed.content));
    } else {
      const number = parsed.type === "deletion" ? parsed.oldNumber : parsed.newNumber;
      const code = cell(documentRef, "diff-code");
      appendHighlightedCode(code, parsed.content, documentRef);
      line.append(cell(documentRef, "diff-line-number", number), code);
    }
    root.append(line);
  }
  return root;
}

function row(type, oldNumber, newNumber, marker, content) {
  return { type, oldNumber, newNumber, marker, content };
}

function collapsedRow(count) {
  return row(
    "collapsed",
    null,
    null,
    "",
    `${count} unmodified ${count === 1 ? "line" : "lines"}`,
  );
}

function lineCount(content) {
  if (!content) return null;
  const lines = String(content).split(/\r?\n/);
  if (lines.at(-1) === "") lines.pop();
  return lines.length;
}

const KEYWORDS = new Set([
  "as", "async", "await", "break", "case", "catch", "class", "const",
  "continue", "def", "default", "do", "else", "enum", "export", "extends",
  "false", "finally", "for", "from", "function", "if", "implements", "import",
  "in", "interface", "let", "match", "new", "none", "null", "of", "package",
  "pass", "private", "protected", "public", "raise", "return", "static", "struct",
  "switch", "this", "throw", "true", "try", "type", "var", "while", "with",
  "yield",
]);

const TOKEN_PATTERN = /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\/\/.*|#.*|\b[A-Za-z_$][\w$]*\b|\b\d+(?:\.\d+)?\b)/g;

function appendHighlightedCode(target, source, documentRef) {
  let cursor = 0;
  for (const match of source.matchAll(TOKEN_PATTERN)) {
    const index = match.index ?? 0;
    if (index > cursor) target.append(documentRef.createTextNode(source.slice(cursor, index)));
    const value = match[0];
    const token = documentRef.createElement("span");
    token.className = `diff-token ${tokenType(value)}`;
    token.textContent = value;
    target.append(token);
    cursor = index + value.length;
  }
  if (cursor < source.length) target.append(documentRef.createTextNode(source.slice(cursor)));
}

function tokenType(value) {
  const lower = value.toLowerCase();
  if (KEYWORDS.has(lower)) return "keyword";
  if (/^['"`]/.test(value)) return "string";
  if (/^\d/.test(value)) return "number";
  if (/^(?:\/\/|#)/.test(value)) return "comment";
  return "identifier";
}

function cell(documentRef, className, value = "") {
  const node = documentRef.createElement("span");
  node.className = className;
  node.textContent = value ?? "";
  return node;
}
