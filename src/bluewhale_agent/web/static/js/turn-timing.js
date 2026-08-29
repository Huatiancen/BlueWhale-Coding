export function turnDurationMs(turn, now = Date.now()) {
  const startedAt = Date.parse(turn.startedAt);
  if (!Number.isFinite(startedAt)) return 0;
  const finishedAt = turn.finishedAt ? Date.parse(turn.finishedAt) : now;
  if (!Number.isFinite(finishedAt)) return 0;
  return Math.max(0, finishedAt - startedAt);
}

export function formatTurnDuration(durationMs, active = false) {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  const duration = minutes ? `${minutes}分钟${seconds}秒` : `${seconds}秒`;
  return `${active ? "已用时" : "用时"} ${duration}`;
}

export function refreshActiveTurnDurations(root, now = Date.now()) {
  for (const label of root.querySelectorAll('.work-duration[data-active="true"]')) {
    label.textContent = formatTurnDuration(
      turnDurationMs({ startedAt: label.dataset.startedAt, finishedAt: null }, now),
      true,
    );
  }
}
