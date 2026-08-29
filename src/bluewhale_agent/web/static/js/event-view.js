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
