export function pendingFollowUps(events) {
  const resolved = new Set();
  for (const stored of events) {
    const kind = stored.event?.kind;
    if (!["follow_up_steered", "follow_up_withdrawn", "follow_up_started"].includes(kind)) {
      continue;
    }
    const id = stored.event?.payload?.follow_up_id;
    if (id) resolved.add(id);
  }
  return events
    .filter((stored) => stored.event?.kind === "follow_up_queued")
    .map((stored) => stored.event?.payload?.follow_up)
    .filter((followUp) => followUp?.id && !resolved.has(followUp.id));
}
