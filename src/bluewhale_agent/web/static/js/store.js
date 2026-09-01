import { projectKey } from "./project-groups.js";

export const state = {
  runs: [],
  activeRunId: null,
  events: new Map(),
  connectionState: "idle",
  permissionMode: "balanced",
  collapsedProjects: new Set(),
};

const subscribers = new Set();

export function subscribe(listener) {
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}

export function setRuns(runs) {
  state.runs = [...runs];
  if (state.activeRunId && !state.runs.some((run) => run.id === state.activeRunId)) {
    state.activeRunId = null;
  }
  const projectKeys = new Set(state.runs.map(projectKey));
  state.collapsedProjects = new Set(
    [...state.collapsedProjects].filter((key) => projectKeys.has(key)),
  );
  notify();
}

export function upsertRun(run) {
  const index = state.runs.findIndex((item) => item.id === run.id);
  if (index === -1) {
    state.runs = [...state.runs, run];
  } else {
    state.runs = state.runs.map((item, current) => (current === index ? run : item));
  }
  notify();
}

export function selectRun(runId) {
  state.activeRunId = runId;
  const selected = state.runs.find((run) => run.id === runId);
  if (selected) state.collapsedProjects.delete(projectKey(selected));
  notify();
}

export function toggleProjectCollapsed(key) {
  const selected = state.runs.find((run) => run.id === state.activeRunId);
  if (selected && projectKey(selected) === key) return;
  const next = new Set(state.collapsedProjects);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  state.collapsedProjects = next;
  notify();
}

export function addEvent(runId, storedEvent) {
  const existing = state.events.get(runId) || [];
  if (existing.some((item) => item.sequence === storedEvent.sequence)) {
    return;
  }
  const next = [...existing, storedEvent].sort((left, right) => left.sequence - right.sequence);
  state.events.set(runId, next);
  const run = state.runs.find((item) => item.id === runId);
  if (
    !run?.historical &&
    storedEvent.event.kind === "state_changed" &&
    storedEvent.event.payload.status
  ) {
    state.runs = state.runs.map((run) =>
      run.id === runId ? { ...run, status: storedEvent.event.payload.status } : run,
    );
  }
  notify();
}

export function setRunEvents(runId, storedEvents) {
  const unique = new Map();
  for (const storedEvent of storedEvents) unique.set(storedEvent.sequence, storedEvent);
  state.events.set(
    runId,
    [...unique.values()].sort((left, right) => left.sequence - right.sequence),
  );
  notify();
}

export function setConnectionState(connectionState) {
  state.connectionState = connectionState;
  notify();
}

export function setPermissionMode(permissionMode) {
  state.permissionMode = permissionMode;
  notify();
}

export function activeRun() {
  return state.runs.find((run) => run.id === state.activeRunId) || null;
}

export function activeEvents() {
  return state.events.get(state.activeRunId) || [];
}

function notify() {
  for (const listener of subscribers) {
    listener(state);
  }
}
