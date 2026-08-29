import assert from "node:assert/strict";
import test from "node:test";

import { createStreamGuard } from "../../../src/bluewhale_agent/web/static/js/stream-guard.js";

test("a callback from a replaced stream cannot affect the current stream", () => {
  const guard = createStreamGuard();
  const firstIsCurrent = guard.begin();

  guard.invalidate();
  const secondIsCurrent = guard.begin();

  assert.equal(firstIsCurrent(), false);
  assert.equal(secondIsCurrent(), true);
});

test("closing the current stream invalidates its callbacks", () => {
  const guard = createStreamGuard();
  const isCurrent = guard.begin();

  guard.invalidate();

  assert.equal(isCurrent(), false);
});
