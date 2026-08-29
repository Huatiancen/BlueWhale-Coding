import assert from "node:assert/strict";
import test from "node:test";

import {
  groupRunsByProject,
  workspaceSelectionStartsNewTask,
} from "../../../src/bluewhale_agent/web/static/js/project-groups.js";

function run(id, workspace, workspaceName, createdAt, workspaceAvailable = true) {
  return {
    id,
    task: `Task ${id}`,
    workspace,
    workspace_name: workspaceName,
    workspace_available: workspaceAvailable,
    created_at: createdAt,
  };
}

test("groups by workspace path and keeps same-name projects separate", () => {
  const groups = groupRunsByProject([
    run("one", "/Users/me/a/demo", "demo", "2026-08-29T01:00:00Z"),
    run("two", "/Users/me/b/demo", "demo", "2026-08-29T02:00:00Z"),
  ]);

  assert.equal(groups.length, 2);
  assert.deepEqual(groups.map((group) => group.key), ["/Users/me/b/demo", "/Users/me/a/demo"]);
});

test("sorts projects and tasks by their newest task", () => {
  const groups = groupRunsByProject([
    run("old-a", "/a", "A", "2026-08-29T01:00:00Z"),
    run("new-b", "/b", "B", "2026-08-29T04:00:00Z"),
    run("new-a", "/a", "A", "2026-08-29T03:00:00Z"),
  ]);

  assert.deepEqual(groups.map((group) => group.name), ["B", "A"]);
  assert.deepEqual(groups[1].runs.map((item) => item.id), ["new-a", "old-a"]);
});

test("marks a project unavailable only when no run reports an available workspace", () => {
  const groups = groupRunsByProject([
    run("old", "/a", "A", "2026-08-29T01:00:00Z", false),
    run("new", "/a", "A", "2026-08-29T02:00:00Z", true),
    run("missing", "/missing", "Missing", "2026-08-29T03:00:00Z", false),
  ]);

  assert.equal(groups.find((group) => group.key === "/a").available, true);
  assert.equal(groups.find((group) => group.key === "/missing").available, false);
});

test("places malformed records in a stable unknown project without mutating input", () => {
  const runs = [{ id: "unknown", task: "Unknown" }];
  const before = JSON.stringify(runs);

  const groups = groupRunsByProject(runs);

  assert.equal(groups[0].key, "__unknown__");
  assert.equal(groups[0].name, "未知项目");
  assert.equal(JSON.stringify(runs), before);
});

test("starts a new task when an open conversation switches projects", () => {
  const activeRun = run("active", "/Users/me/old", "old", "2026-08-29T01:00:00Z");

  assert.equal(
    workspaceSelectionStartsNewTask(activeRun, { display_path: "/Users/me/new" }),
    true,
  );
  assert.equal(
    workspaceSelectionStartsNewTask(activeRun, { display_path: "/Users/me/old" }),
    false,
  );
  assert.equal(
    workspaceSelectionStartsNewTask(null, { display_path: "/Users/me/new" }),
    false,
  );
});
