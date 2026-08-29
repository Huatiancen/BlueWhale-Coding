export function parseUnifiedDiff(source) {
  const lines = String(source || "").split(/\r?\n/);
  if (lines.at(-1) === "") lines.pop();
  const rows = [];
  let oldLine = null;
  let newLine = null;

  for (const raw of lines) {
    const hunk = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
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
  return rows;
}

export function renderUnifiedDiff(source, documentRef = document) {
  const root = documentRef.createElement("div");
  root.className = "artifact-diff";
  root.setAttribute("role", "table");
  root.setAttribute("aria-label", "文件差异");
  for (const parsed of parseUnifiedDiff(source)) {
    const line = documentRef.createElement("div");
    line.className = `diff-line ${parsed.type}`;
    line.setAttribute("role", "row");
    line.append(
      cell(documentRef, "diff-line-number old", parsed.oldNumber),
      cell(documentRef, "diff-line-number new", parsed.newNumber),
      cell(documentRef, "diff-marker", parsed.marker),
      cell(documentRef, "diff-code", parsed.content),
    );
    root.append(line);
  }
  return root;
}

function row(type, oldNumber, newNumber, marker, content) {
  return { type, oldNumber, newNumber, marker, content };
}

function cell(documentRef, className, value) {
  const node = documentRef.createElement("span");
  node.className = className;
  node.textContent = value ?? "";
  return node;
}
