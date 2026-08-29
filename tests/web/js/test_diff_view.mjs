import assert from "node:assert/strict";
import test from "node:test";

import { parseUnifiedDiff } from "../../../src/bluewhale_agent/web/static/js/diff-view.js";

test("parses unified diff rows with old and new line numbers", () => {
  const rows = parseUnifiedDiff(
    "--- a/main.c\n+++ b/main.c\n@@ -2,2 +2,3 @@\n int value = 1;\n-old();\n+new_call();\n+return 0;\n",
  );

  assert.deepEqual(
    rows.map(({ type, oldNumber, newNumber, marker, content }) => ({
      type,
      oldNumber,
      newNumber,
      marker,
      content,
    })),
    [
      { type: "file", oldNumber: null, newNumber: null, marker: "", content: "--- a/main.c" },
      { type: "file", oldNumber: null, newNumber: null, marker: "", content: "+++ b/main.c" },
      { type: "hunk", oldNumber: null, newNumber: null, marker: "", content: "@@ -2,2 +2,3 @@" },
      { type: "context", oldNumber: 2, newNumber: 2, marker: " ", content: "int value = 1;" },
      { type: "deletion", oldNumber: 3, newNumber: null, marker: "-", content: "old();" },
      { type: "addition", oldNumber: null, newNumber: 3, marker: "+", content: "new_call();" },
      { type: "addition", oldNumber: null, newNumber: 4, marker: "+", content: "return 0;" },
    ],
  );
});

test("keeps diff metadata readable without assigning line numbers", () => {
  assert.deepEqual(parseUnifiedDiff("\\ No newline at end of file"), [
    {
      type: "meta",
      oldNumber: null,
      newNumber: null,
      marker: "",
      content: "\\ No newline at end of file",
    },
  ]);
});
