export function findPendingApproval(events) {
  const resolvedIds = new Set(
    events
      .filter(({ event } = {}) => event?.kind === "approval_resolved")
      .map(({ event }) => event.payload?.approval?.id)
      .filter(Boolean),
  );
  return events.findLast(({ event } = {}) => {
    const approval = event?.payload?.approval;
    return (
      event?.kind === "approval_requested" &&
      approval?.id &&
      approval.status === "pending" &&
      !resolvedIds.has(approval.id)
    );
  }) || null;
}

export function instructionEvidence(events) {
  return events
    .filter(({ event } = {}) => event?.kind === "instructions_applied")
    .map(({ event }) => ({
      actionId: event.payload?.action_id || "",
      target: event.payload?.target || "",
      sources: (event.payload?.documents || [])
        .map((document) => document.source)
        .filter(Boolean),
    }));
}
