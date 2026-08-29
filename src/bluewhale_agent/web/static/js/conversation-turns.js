export function conversationTimeline(run, events) {
  return splitTurns(run, events).flatMap((turn) => turnTimeline(turn));
}

function splitTurns(run, events) {
  const turns = [];
  let current = null;

  events.forEach((stored, eventIndex) => {
    const isStart = stored.event?.kind === "run_started";
    if (isStart) {
      if (current) turns.push(current);
      const requestedTask = stored.event.payload?.task;
      current = {
        task: typeof requestedTask === "string" ? requestedTask.trim() : "",
        items: [],
      };
    } else if (!current) {
      current = {
        task: typeof run?.task === "string" ? run.task.trim() : "",
        items: [],
      };
    }
    current.items.push({ stored, eventIndex });
  });

  if (current) turns.push(current);
  if (!turns.length && typeof run?.task === "string" && run.task.trim()) {
    turns.push({ task: run.task.trim(), items: [] });
  }
  return turns;
}

function turnTimeline(turn) {
  const timeline = [];
  const mutationActions = new Map();
  const legacyFiles = new Set();
  let hasPersistedChanges = false;
  const storedEvents = turn.items.map(({ stored }) => stored);
  const firstItem = turn.items[0];
  const start = turn.items.find(({ stored }) => stored.event?.kind === "run_started");
  const finish = turn.items.findLast(
    ({ stored }) => stored.event?.kind === "run_finished",
  );

  if (turn.task) {
    timeline.push({
      kind: "user",
      content: turn.task,
      eventIndex: start?.eventIndex ?? firstItem?.eventIndex ?? -1,
    });
  }
  timeline.push({
    kind: "work",
    events: storedEvents,
    modelNarration: storedEvents
      .filter(
        (stored) =>
          stored.event?.kind === "model_response" &&
          isProcessModelResponse(stored.event.payload),
      )
      .map((stored) => stored.event.payload.content?.trim())
      .filter(Boolean),
    startedAt: eventTime(start?.stored || firstItem?.stored),
    finishedAt: eventTime(finish?.stored),
    active: !finish,
    eventIndex: start?.eventIndex ?? firstItem?.eventIndex ?? -1,
  });

  for (const { stored, eventIndex } of turn.items) {
    const kind = stored.event?.kind;
    const payload = stored.event?.payload || {};
    if (
      kind === "action_requested" &&
      ["write_file", "apply_patch"].includes(payload.action?.tool_name)
    ) {
      mutationActions.set(payload.action.id, payload.action.arguments?.path);
    } else if (
      kind === "model_response" &&
      typeof payload.content === "string" &&
      payload.content &&
      !isProcessModelResponse(payload)
    ) {
      timeline.push({ kind: "assistant", content: payload.content, eventIndex });
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
    }
    if (kind === "observation_received" && payload.observation?.status === "success") {
      const path = mutationActions.get(payload.observation?.action_id);
      if (path) legacyFiles.add(path);
    }
  }
  return timeline;
}

export function isProcessModelResponse(payload) {
  return (
    payload?.finish_reason === "tool_calls" ||
    (Array.isArray(payload?.tool_calls) && payload.tool_calls.length > 0)
  );
}

function eventTime(stored) {
  return stored?.event?.occurred_at || stored?.recorded_at || null;
}
