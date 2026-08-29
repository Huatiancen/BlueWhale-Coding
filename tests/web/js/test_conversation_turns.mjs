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
      { kind: "work", content: undefined },
      { kind: "assistant", content: "第一轮回答" },
      { kind: "user", content: "继续追问" },
      { kind: "work", content: undefined },
      { kind: "assistant", content: "第二轮回答" },
    ],
  );
});

test("keeps failed turn results visible while hiding successful completion strips", () => {
  const timeline = conversationTimeline(
    { task: "运行任务" },
    [
      stored(1, "run_started", { task: "运行任务" }),
      stored(2, "run_finished", { status: "failed", stop_reason: "tool_error" }),
    ],
  );

  const result = timeline.find((entry) => entry.kind === "result");
  assert.equal(result.payload.status, "failed");
  assert.equal(result.payload.stop_reason, "tool_error");
});

test("falls back to the run title for imported history without run_started", () => {
  const timeline = conversationTimeline(
    { task: "导入的旧任务" },
    [stored(1, "model_response", { content: "旧回答" })],
  );

  assert.equal(timeline[0].kind, "user");
  assert.equal(timeline[0].content, "导入的旧任务");
  assert.equal(timeline[1].kind, "work");
  assert.equal(timeline[2].kind, "assistant");
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

  assert.equal(timeline[2].kind, "error");
  assert.equal(timeline[2].observation.summary, "命令失败");
});

test("places a persisted changeset in the turn that produced it", () => {
  const payload = { files: [{ path: "src/app.py", additions: 2, deletions: 1 }] };
  const timeline = conversationTimeline(
    { task: "修改代码" },
    [
      stored(1, "run_started", { task: "修改代码" }),
      stored(2, "changeset_recorded", payload),
      stored(3, "run_finished", { status: "completed" }),
    ],
  );

  assert.equal(timeline[2].kind, "changeset");
  assert.equal(timeline[2].payload.files[0].path, "src/app.py");
  assert.equal(timeline.some((entry) => entry.kind === "result"), false);
});

test("builds a source-only fallback card for older mutation history", () => {
  const timeline = conversationTimeline(
    { task: "旧任务" },
    [
      stored(1, "run_started", { task: "旧任务" }),
      stored(2, "action_requested", {
        action: { id: "write-1", tool_name: "write_file", arguments: { path: "old.py" } },
      }),
      stored(3, "observation_received", {
        observation: { action_id: "write-1", status: "success", metadata: { path: "old.py" } },
      }),
      stored(4, "run_finished", { status: "completed" }),
    ],
  );

  assert.equal(timeline[2].kind, "changeset");
  assert.equal(timeline[2].payload.legacy, true);
  assert.equal(timeline[2].payload.files[0].path, "old.py");
});

test("keeps work events isolated inside their own conversation turn", () => {
  const timeline = conversationTimeline(
    { task: "第一轮" },
    [
      stored(1, "run_started", { task: "第一轮" }),
      stored(2, "action_requested", { action: { id: "read", tool_name: "read_file" } }),
      stored(3, "run_finished", { status: "completed" }),
      stored(4, "run_started", { task: "第二轮" }),
      stored(5, "action_requested", { action: { id: "run", tool_name: "run_command" } }),
      stored(6, "run_finished", { status: "completed" }),
    ],
  );
  const work = timeline.filter((entry) => entry.kind === "work");

  assert.equal(work.length, 2);
  assert.deepEqual(
    work.map((entry) =>
      entry.events
        .filter((event) => event.event.kind === "action_requested")
        .map((event) => event.event.payload.action.tool_name),
    ),
    [["read_file"], ["run_command"]],
  );
});

function stored(sequence, kind, payload) {
  return { sequence, event: { kind, payload } };
}
