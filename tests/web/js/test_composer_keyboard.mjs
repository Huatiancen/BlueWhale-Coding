import assert from "node:assert/strict";
import test from "node:test";

import { shouldSubmitComposer } from "../../../src/bluewhale_agent/web/static/js/composer-keyboard.js";

test("submits a composer message with Enter", () => {
  assert.equal(
    shouldSubmitComposer({ key: "Enter", shiftKey: false, isComposing: false }),
    true,
  );
});

test("keeps Shift+Enter available for a newline", () => {
  assert.equal(
    shouldSubmitComposer({ key: "Enter", shiftKey: true, isComposing: false }),
    false,
  );
});

test("does not submit while an input method is composing text", () => {
  assert.equal(
    shouldSubmitComposer({ key: "Enter", shiftKey: false, isComposing: true }),
    false,
  );
});

test("ignores keys other than Enter", () => {
  assert.equal(
    shouldSubmitComposer({ key: "a", shiftKey: false, isComposing: false }),
    false,
  );
});
