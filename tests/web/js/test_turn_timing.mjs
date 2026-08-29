import assert from "node:assert/strict";
import test from "node:test";

import { formatTurnDuration, turnDurationMs } from "../../../src/bluewhale_agent/web/static/js/turn-timing.js";

test("formats completed turn duration like Codex", () => {
  assert.equal(formatTurnDuration(257_000, false), "用时 4分钟17秒");
  assert.equal(formatTurnDuration(9_000, false), "用时 9秒");
});

test("computes an active turn duration from the current time", () => {
  assert.equal(
    turnDurationMs({ startedAt: "2026-08-29T12:00:00Z", finishedAt: null }, Date.parse("2026-08-29T12:00:12Z")),
    12_000,
  );
  assert.equal(formatTurnDuration(12_000, true), "已用时 12秒");
});
