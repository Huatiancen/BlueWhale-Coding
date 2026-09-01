import assert from "node:assert/strict";
import test from "node:test";

import {
  addEvent,
  selectRun,
  setRunEvents,
  setRuns,
  state,
  toggleProjectCollapsed,
} from "../../../src/bluewhale_agent/web/static/js/store.js";

const runs = [
  { id: "a", workspace: "/project-a" },
  { id: "b", workspace: "/project-b" },
];

test("projects start expanded and the active project cannot be collapsed", () => {
  setRuns(runs);
  selectRun("a");

  toggleProjectCollapsed("/project-a");

  assert.equal(state.collapsedProjects.has("/project-a"), false);
});

test("toggles inactive projects and expands one when its task is selected", () => {
  setRuns(runs);
  selectRun("a");

  toggleProjectCollapsed("/project-b");
  assert.equal(state.collapsedProjects.has("/project-b"), true);
  selectRun("b");
  assert.equal(state.collapsedProjects.has("/project-b"), false);
});

test("removes collapsed keys when a project disappears", () => {
  setRuns(runs);
  selectRun("a");
  toggleProjectCollapsed("/project-b");

  setRuns([runs[0]]);

  assert.deepEqual([...state.collapsedProjects], []);
});

test("loading history keeps the homepage selected", () => {
  selectRun(null);

  setRuns(runs);

  assert.equal(state.activeRunId, null);
});

test("refreshing history preserves an explicitly selected task", () => {
  setRuns(runs);
  selectRun("a");

  setRuns(runs);

  assert.equal(state.activeRunId, "a");
});

test("historical event hydration preserves the authoritative terminal status", () => {
  setRuns([{ id: "history", workspace: "/project", historical: true, status: "stopped" }]);

  setRunEvents("history", [
    stored(1, "state_changed", { status: "running" }),
    stored(2, "run_finished", { status: "stopped", stop_reason: "step_limit" }),
  ]);

  assert.equal(state.runs[0].status, "stopped");
  assert.deepEqual(
    state.events.get("history").map((item) => item.sequence),
    [1, 2],
  );
});

test("live state changes still update the run summary", () => {
  setRuns([{ id: "live", workspace: "/project", historical: false, status: "running" }]);

  addEvent("live", stored(1, "state_changed", { status: "verifying" }));

  assert.equal(state.runs[0].status, "verifying");
});

function stored(sequence, kind, payload) {
  return { sequence, event: { kind, payload } };
}
