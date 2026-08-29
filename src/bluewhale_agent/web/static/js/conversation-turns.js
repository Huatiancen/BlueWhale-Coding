export function conversationTimeline(run, events) {
  const timeline = [];
  const hasUserTurn = events.some(
    (stored) =>
      stored.event?.kind === "run_started" &&
      typeof stored.event.payload?.task === "string" &&
      stored.event.payload.task.trim(),
  );
  if (!hasUserTurn && typeof run?.task === "string" && run.task.trim()) {
    timeline.push({ kind: "user", content: run.task.trim(), eventIndex: -1 });
  }

  events.forEach((stored, eventIndex) => {
    const kind = stored.event?.kind;
    const payload = stored.event?.payload || {};
    if (kind === "run_started" && typeof payload.task === "string" && payload.task.trim()) {
      timeline.push({ kind: "user", content: payload.task.trim(), eventIndex });
    } else if (
      kind === "model_response" &&
      typeof payload.content === "string" &&
      payload.content
    ) {
      timeline.push({ kind: "assistant", content: payload.content, eventIndex });
    } else if (
      kind === "observation_received" &&
      payload.observation?.status !== "success"
    ) {
      timeline.push({ kind: "error", observation: payload.observation, eventIndex });
    } else if (kind === "run_finished") {
      timeline.push({ kind: "result", payload, eventIndex });
    }
  });
  return timeline;
}
