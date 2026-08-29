import assert from "node:assert/strict";
import test from "node:test";

import {
  selectRun,
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
