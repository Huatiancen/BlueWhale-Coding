const ACTIVE_STATUSES = new Set(["initializing", "running", "waiting_approval", "verifying"]);

export function shouldCloseRunStream(sourceRun, refreshedRun) {
  return Boolean(
    !sourceRun?.historical &&
    refreshedRun &&
    !ACTIVE_STATUSES.has(refreshedRun.status),
  );
}
