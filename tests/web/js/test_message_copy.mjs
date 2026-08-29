import assert from "node:assert/strict";
import test from "node:test";

import { createMessageCopyButton } from "../../../src/bluewhale_agent/web/static/js/message-copy.js";

class FakeButton {
  constructor() {
    this.attributes = {};
    this.className = "";
    this.disabled = false;
    this.listeners = new Map();
    this.textContent = "";
    this.title = "";
    this.type = "";
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  addEventListener(name, listener) {
    this.listeners.set(name, listener);
  }

  click() {
    return this.listeners.get("click")();
  }
}

function harness({ reject = false } = {}) {
  const writes = [];
  const errors = [];
  const timers = [];
  const cleared = [];
  return {
    writes,
    errors,
    timers,
    cleared,
    options: {
      documentRef: { createElement: () => new FakeButton() },
      clipboard: {
        async writeText(value) {
          if (reject) throw new Error("denied");
          writes.push(value);
        },
      },
      onError: (message) => errors.push(message),
      setTimer(callback) {
        timers.push(callback);
        return timers.length;
      },
      clearTimer(timerId) {
        cleared.push(timerId);
      },
    },
  };
}

test("copies the exact raw message and exposes an accessible label", async () => {
  const state = harness();
  const button = createMessageCopyButton("**原始 Markdown**", state.options);

  await button.click();

  assert.deepEqual(state.writes, ["**原始 Markdown**"]);
  assert.equal(button.attributes["aria-label"], "已复制");
  assert.equal(button.textContent, "✓");
  assert.equal(button.disabled, false);
});

test("restores the copy affordance and replaces an older restore timer", async () => {
  const state = harness();
  const button = createMessageCopyButton("message", state.options);

  await button.click();
  await button.click();
  state.timers.at(-1)();

  assert.deepEqual(state.cleared, [1]);
  assert.equal(button.attributes["aria-label"], "复制消息");
  assert.equal(button.textContent, "⧉");
});

test("reports clipboard failure without showing a success state", async () => {
  const state = harness({ reject: true });
  const button = createMessageCopyButton("message", state.options);

  await button.click();

  assert.deepEqual(state.errors, ["无法复制消息，请检查剪贴板权限。"]);
  assert.equal(button.attributes["aria-label"], "复制消息");
  assert.equal(button.textContent, "⧉");
  assert.equal(button.disabled, false);
});
