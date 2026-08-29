export function conversationTimeline(run, events) {
  const timeline = [];
  const mutationActions = new Map();
  const legacyFiles = new Set();
  let hasPersistedChanges = false;
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
      mutationActions.clear();
      legacyFiles.clear();
      hasPersistedChanges = false;
      timeline.push({ kind: "user", content: payload.task.trim(), eventIndex });
    } else if (
      kind === "action_requested" &&
      ["write_file", "apply_patch"].includes(payload.action?.tool_name)
    ) {
      mutationActions.set(payload.action.id, payload.action.arguments?.path);
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
    } else if (kind === "changeset_recorded" && Array.isArray(payload.files)) {
      hasPersistedChanges = true;
      timeline.push({ kind: "changeset", payload, eventIndex });
    } else if (kind === "run_finished") {
      if (!hasPersistedChanges && legacyFiles.size) {
        timeline.push({
          kind: "changeset",
          payload: {
            legacy: true,
            additions: 0,
            deletions: 0,
            files: [...legacyFiles].sort().map((path) => ({ path })),
          },
          eventIndex,
        });
      }
      timeline.push({ kind: "result", payload, eventIndex });
    }
    if (kind === "observation_received" && payload.observation?.status === "success") {
      const path = mutationActions.get(payload.observation?.action_id);
      if (path) legacyFiles.add(path);
    }
  });
  return timeline;
}
