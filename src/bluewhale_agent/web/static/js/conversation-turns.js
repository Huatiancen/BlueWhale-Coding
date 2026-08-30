export function conversationTimeline(run, events) {
  const revertedChangesets = new Set(
    events
      .filter((stored) => stored.event?.kind === "changeset_reverted")
      .map((stored) => Number(stored.event.payload?.changeset_sequence))
      .filter(Number.isInteger),
  );
  return splitTurns(run, events).flatMap((turn) =>
    turnTimeline(turn, revertedChangesets),
  );
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

function turnTimeline(turn, revertedChangesets) {
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
  const reasoningDelta = storedEvents
    .filter(
      (stored) =>
        stored.event?.kind === "model_delta" &&
        stored.event.payload?.kind === "reasoning",
    )
    .map((stored) => stored.event.payload?.content || "")
    .join("")
    .trim();
  const completedAnswer = storedEvents.some(
    (stored) =>
      stored.event?.kind === "model_response" &&
      typeof stored.event.payload?.content === "string" &&
      stored.event.payload.content &&
      !isProcessModelResponse(stored.event.payload),
  );
  const deliveredInstructions = new Set(
    storedEvents
      .filter((stored) => stored.event?.kind === "instruction_delivered")
      .map((stored) => stored.event.payload?.instruction_id),
  );
  const withdrawnInstructions = new Set(
    storedEvents
      .filter((stored) => stored.event?.kind === "instruction_withdrawn")
      .map((stored) => stored.event.payload?.instruction_id),
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
      .filter(Boolean)
      .concat(reasoningDelta ? [reasoningDelta] : []),
    startedAt: eventTime(start?.stored || firstItem?.stored),
    finishedAt: eventTime(finish?.stored),
    active: !finish,
    eventIndex: start?.eventIndex ?? firstItem?.eventIndex ?? -1,
  });

  if (!completedAnswer) {
    const answerDeltas = turn.items.filter(
      ({ stored }) =>
        stored.event?.kind === "model_delta" &&
        stored.event.payload?.kind === "answer",
    );
    const streamedAnswer = answerDeltas
      .map(({ stored }) => stored.event.payload?.content || "")
      .join("");
    if (streamedAnswer) {
      timeline.push({
        kind: "assistant",
        content: streamedAnswer,
        eventIndex: answerDeltas.at(-1)?.eventIndex ?? -1,
        streaming: true,
      });
    }
  }

  for (const { stored, eventIndex } of turn.items) {
    const kind = stored.event?.kind;
    const payload = stored.event?.payload || {};
    if (kind === "instruction_queued") {
      const instruction = payload.instruction || {};
      if (!withdrawnInstructions.has(instruction.id)) {
        timeline.push({
          kind: "user",
          content: instruction.content || "",
          instructionId: instruction.id,
          queued: !deliveredInstructions.has(instruction.id),
          eventIndex,
        });
      }
    } else if (
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
      timeline.push({
        kind: "changeset",
        payload,
        eventSequence: stored.sequence,
        reverted: revertedChangesets.has(stored.sequence),
        eventIndex,
      });
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
    payload?.intermediate === true ||
    payload?.finish_reason === "tool_calls" ||
    (Array.isArray(payload?.tool_calls) && payload.tool_calls.length > 0)
  );
}

function eventTime(stored) {
  return stored?.event?.occurred_at || stored?.recorded_at || null;
}
