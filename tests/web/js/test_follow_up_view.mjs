import assert from "node:assert/strict";
import test from "node:test";

import { pendingFollowUps } from "../../../src/bluewhale_agent/web/static/js/follow-up-view.js";

test("returns only unresolved queued follow-ups in FIFO order", () => {
  const events = [
    stored(1, "follow_up_queued", followUp("one", "第一条")),
    stored(2, "follow_up_queued", followUp("two", "第二条")),
    stored(3, "follow_up_queued", followUp("three", "第三条")),
    stored(4, "follow_up_steered", { follow_up_id: "two" }),
    stored(5, "follow_up_withdrawn", { follow_up_id: "three" }),
  ];

  assert.deepEqual(pendingFollowUps(events), [
    { id: "one", content: "第一条", created_at: "2026-08-31T00:00:00Z" },
  ]);
});

test("started follow-up leaves the pending dock", () => {
  const events = [
    stored(1, "follow_up_queued", followUp("next", "下一轮")),
    stored(2, "follow_up_started", { follow_up_id: "next", content: "下一轮" }),
  ];

  assert.deepEqual(pendingFollowUps(events), []);
});

function followUp(id, content) {
  return {
    follow_up: { id, content, created_at: "2026-08-31T00:00:00Z" },
  };
}

function stored(sequence, kind, payload) {
  return { sequence, event: { kind, payload } };
}
