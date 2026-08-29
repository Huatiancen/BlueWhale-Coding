const UNKNOWN_PROJECT = "__unknown__";

export function groupRunsByProject(runs) {
  const grouped = new Map();
  for (const run of runs) {
    const key = projectKey(run);
    if (!grouped.has(key)) {
      grouped.set(key, {
        key,
        name: projectName(run, key),
        available: key !== UNKNOWN_PROJECT && run?.workspace_available !== false,
        latestAt: timestamp(run?.created_at),
        runs: [],
      });
    }
    const group = grouped.get(key);
    group.available ||= key !== UNKNOWN_PROJECT && run?.workspace_available !== false;
    group.latestAt = Math.max(group.latestAt, timestamp(run?.created_at));
    group.runs.push(run);
  }

  const groups = [...grouped.values()];
  for (const group of groups) {
    group.runs.sort(compareRunsNewestFirst);
  }
  return groups.sort(
    (left, right) => right.latestAt - left.latestAt || left.key.localeCompare(right.key),
  );
}

export function projectKey(run) {
  return typeof run?.workspace === "string" && run.workspace.trim()
    ? run.workspace.trim()
    : UNKNOWN_PROJECT;
}

export function workspaceSelectionStartsNewTask(activeRun, selection) {
  if (!activeRun) return false;
  const selectedPath =
    typeof selection?.display_path === "string" ? selection.display_path.trim() : "";
  return Boolean(selectedPath && projectKey(activeRun) !== selectedPath);
}

function projectName(run, key) {
  if (key === UNKNOWN_PROJECT) return "未知项目";
  if (typeof run?.workspace_name === "string" && run.workspace_name.trim()) {
    return run.workspace_name.trim();
  }
  return key.split(/[\\/]/).filter(Boolean).at(-1) || key;
}

function compareRunsNewestFirst(left, right) {
  return (
    timestamp(right?.created_at) - timestamp(left?.created_at) ||
    String(left?.id || "").localeCompare(String(right?.id || ""))
  );
}

function timestamp(value) {
  const parsed = typeof value === "string" ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}
