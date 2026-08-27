const EVENT_TYPES = [
  "run_started",
  "state_changed",
  "model_response",
  "action_requested",
  "observation_received",
  "verification_finished",
  "run_finished",
];

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_error) {
      // Keep the deterministic fallback when an intermediary returns non-JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

export function listRuns() {
  return request("/api/runs");
}

export function getRun(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}`);
}

export function createRun({ task, workspace }) {
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify({ task, workspace }),
  });
}

export function stopRun(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" });
}

export function connectRunEvents(runId, handlers) {
  const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
  source.onopen = () => handlers.onState("connected");
  source.onerror = () => handlers.onState("reconnecting");
  for (const eventType of EVENT_TYPES) {
    source.addEventListener(eventType, (message) => {
      try {
        handlers.onEvent(JSON.parse(message.data));
      } catch (error) {
        handlers.onState("error", `事件解析失败：${error.message}`);
      }
    });
  }
  return () => source.close();
}
