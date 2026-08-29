import assert from "node:assert/strict";
import test from "node:test";

import { homePrompt } from "../../../src/bluewhale_agent/web/static/js/home-prompt.js";

test("invites the user to work in the selected project", () => {
  assert.deepEqual(homePrompt("BlueWhale-Coding"), {
    title: "我们应该在「BlueWhale-Coding」中做些什么？",
    subtitle: "描述目标，BlueWhale 会阅读项目、完成修改并运行验证。",
  });
});

test("keeps the empty homepage concise before a project is selected", () => {
  assert.deepEqual(homePrompt(null), {
    title: "今天想做些什么？",
    subtitle: "从左侧打开一个项目，然后告诉 BlueWhale 你的目标。",
  });
});
