import assert from "node:assert/strict";
import test from "node:test";

import { shouldCloseRunStream } from "../../../src/bluewhale_agent/web/static/js/stream-lifecycle.js";

test("keeps a historical stream open across intermediate finished turns", () => {
  assert.equal(
    shouldCloseRunStream({ historical: true }, { status: "completed" }),
    false,
  );
});

test("keeps a continued stream open while the current turn is still running", () => {
  assert.equal(
    shouldCloseRunStream({ historical: false }, { status: "running" }),
    false,
  );
});

test("closes a live stream after the current turn is confirmed terminal", () => {
  assert.equal(
    shouldCloseRunStream({ historical: false }, { status: "completed" }),
    true,
  );
});
