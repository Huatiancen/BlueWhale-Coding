import assert from "node:assert/strict";
import test from "node:test";

import {
  clampPanelSize,
  nextPanelSizeFromKey,
} from "../../../src/bluewhale_agent/web/static/js/panel-resize.js";

test("clamps dragged panel sizes to their safe range", () => {
  assert.equal(clampPanelSize(120, 190, 420), 190);
  assert.equal(clampPanelSize(280, 190, 420), 280);
  assert.equal(clampPanelSize(600, 190, 420), 420);
});

test("keyboard resize grows toward the configured side", () => {
  const options = { min: 190, max: 420, step: 16, growKey: "ArrowRight" };

  assert.equal(nextPanelSizeFromKey(248, "ArrowRight", options), 264);
  assert.equal(nextPanelSizeFromKey(248, "ArrowLeft", options), 232);
  assert.equal(nextPanelSizeFromKey(248, "Enter", options), 248);
});

test("right inspector grows when its left separator moves left", () => {
  const options = { min: 320, max: 900, step: 16, growKey: "ArrowLeft" };

  assert.equal(nextPanelSizeFromKey(460, "ArrowLeft", options), 476);
  assert.equal(nextPanelSizeFromKey(460, "ArrowRight", options), 444);
});
