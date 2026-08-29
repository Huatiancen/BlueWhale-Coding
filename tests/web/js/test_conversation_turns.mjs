import assert from "node:assert/strict";
import test from "node:test";

import { conversationTimeline } from "../../../src/bluewhale_agent/web/static/js/conversation-turns.js";

test("builds interleaved user and assistant messages from every run", () => {
  const run = { task: "最初的问题" };
  const events = [
    stored(1, "run_started", { task: "最初的问题" }),
    stored(2, "model_response", { content: "第一轮回答" }),
    stored(3, "run_finished", { status: "completed" }),
    stored(4, "run_started", { task: "继续追问" }),
    stored(5, "model_response", { content: "第二轮回答" }),
    stored(6, "run_finished", { status: "completed" }),
  ];

  assert.deepEqual(
    conversationTimeline(run, events).map(({ kind, content }) => ({ kind, content })),
    [
      { kind: "user", content: "最初的问题" },
      { kind: "assistant", content: "第一轮回答" },
      { kind: "result", content: undefined },
      { kind: "user", content: "继续追问" },
      { kind: "assistant", content: "第二轮回答" },
      { kind: "result", content: undefined },
    ],
  );
});

test("falls back to the run title for imported history without run_started", () => {
  const timeline = conversationTimeline(
    { task: "导入的旧任务" },
    [stored(1, "model_response", { content: "旧回答" })],
  );

  assert.equal(timeline[0].kind, "user");
  assert.equal(timeline[0].content, "导入的旧任务");
  assert.equal(timeline[1].kind, "assistant");
});

test("keeps failed observations at their original timeline position", () => {
  const timeline = conversationTimeline(
    { task: "运行检查" },
    [
      stored(1, "run_started", { task: "运行检查" }),
      stored(2, "observation_received", {
        observation: { status: "error", summary: "命令失败" },
      }),
    ],
  );

  assert.equal(timeline[1].kind, "error");
  assert.equal(timeline[1].observation.summary, "命令失败");
});

function stored(sequence, kind, payload) {
  return { sequence, event: { kind, payload } };
}
