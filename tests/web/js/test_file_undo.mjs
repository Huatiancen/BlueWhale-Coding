import assert from "node:assert/strict";
import test from "node:test";

import { conversationTimeline } from "../../../src/bluewhale_agent/web/static/js/conversation-turns.js";

function stored(sequence, kind, payload) {
  return { sequence, event: { kind, payload } };
}

test("marks only the reverted file inside a changeset", () => {
  const timeline = conversationTimeline(
    { task: "fix", status: "completed" },
    [
      stored(1, "run_started", { task: "fix" }),
      stored(2, "changeset_recorded", {
        files: [{ path: "a.py" }, { path: "b.py" }],
      }),
      stored(3, "changeset_files_reverted", {
        changeset_sequence: 2,
        files: ["b.py"],
      }),
    ],
  );

  const changeset = timeline.find((entry) => entry.kind === "changeset");
  assert.deepEqual([...changeset.revertedPaths], ["b.py"]);
  assert.equal(changeset.reverted, false);
});
