import assert from "node:assert/strict";
import test from "node:test";

import {
  findPendingApproval,
  instructionEvidence,
} from "../../../src/bluewhale_agent/web/static/js/event-view.js";

function approvalRequested(id, status = "pending") {
  return {
    event: {
      kind: "approval_requested",
      payload: { approval: { id, status } },
    },
  };
}

function approvalResolved(id, status = "approved") {
  return {
    event: {
      kind: "approval_resolved",
      payload: { approval: { id, status } },
    },
  };
}

test("returns the latest unresolved approval", () => {
  const first = approvalRequested("first");
  const second = approvalRequested("second");

  assert.equal(findPendingApproval([first, second]), second);
});

test("does not return an approval after it is resolved", () => {
  assert.equal(
    findPendingApproval([approvalRequested("approval-1"), approvalResolved("approval-1")]),
    null,
  );
});

test("ignores every resolved approval even when resolution events are duplicated", () => {
  assert.equal(
    findPendingApproval([
      approvalRequested("approval-1"),
      approvalResolved("approval-1"),
      approvalResolved("approval-1"),
    ]),
    null,
  );
});

test("ignores malformed and non-pending approval events", () => {
  assert.equal(
    findPendingApproval([
      {},
      { event: { kind: "approval_requested", payload: {} } },
      approvalRequested("approval-1", "cancelled"),
    ]),
    null,
  );
});

test("returns an older request when only the newer request was resolved", () => {
  const first = approvalRequested("first");
  const second = approvalRequested("second");

  assert.equal(findPendingApproval([first, second, approvalResolved("second")]), first);
});

test("projects scoped instruction sources without exposing full rule text", () => {
  const evidence = instructionEvidence([
    {
      event: {
        kind: "instructions_applied",
        payload: {
          action_id: "read-1",
          target: "src/app.py",
          documents: [
            { source: "AGENTS.md", scope: ".", summary: "Root rule" },
            { source: "src/AGENTS.md", scope: "src", summary: "Source rule" },
          ],
        },
      },
    },
  ]);

  assert.deepEqual(evidence, [
    {
      actionId: "read-1",
      target: "src/app.py",
      sources: ["AGENTS.md", "src/AGENTS.md"],
    },
  ]);
});
