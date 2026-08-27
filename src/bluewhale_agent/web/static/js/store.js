export const state = {
  runs: [],
  activeRunId: null,
  events: new Map(),
  connectionState: "idle",
  selectedPanel: "evidence",
};

const subscribers = new Set();

export function subscribe(listener) {
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}

export function setRuns(runs) {
  state.runs = [...runs];
  if (!state.activeRunId && state.runs.length) {
    state.activeRunId = state.runs[state.runs.length - 1].id;
  }
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
  notify();
}

export function addEvent(runId, storedEvent) {
  const existing = state.events.get(runId) || [];
  if (existing.some((item) => item.sequence === storedEvent.sequence)) {
    return;
  }
  const next = [...existing, storedEvent].sort((left, right) => left.sequence - right.sequence);
  state.events.set(runId, next);
  if (storedEvent.event.kind === "state_changed" && storedEvent.event.payload.status) {
    state.runs = state.runs.map((run) =>
      run.id === runId ? { ...run, status: storedEvent.event.payload.status } : run,
    );
  }
  notify();
}

export function setConnectionState(connectionState) {
  state.connectionState = connectionState;
  notify();
}

export function setSelectedPanel(selectedPanel) {
  state.selectedPanel = selectedPanel;
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
