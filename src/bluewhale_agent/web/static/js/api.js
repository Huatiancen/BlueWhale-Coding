const EVENT_TYPES = [
  "run_started",
  "state_changed",
  "model_response",
  "action_requested",
  "approval_requested",
  "approval_resolved",
  "observation_received",
  "verification_finished",
  "changeset_recorded",
  "changeset_reverted",
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

export function getRunFile(runId, path) {
  const query = new URLSearchParams({ path });
  return request(`/api/runs/${encodeURIComponent(runId)}/files?${query}`);
}

export function createRun({ task, workspace, workspaceGrantId, permissionMode }) {
  const body = { task, permission_mode: permissionMode };
  if (workspaceGrantId) body.workspace_grant_id = workspaceGrantId;
  else body.workspace = workspace || ".";
  return request("/api/runs", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function continueRun(runId, { task, workspace, workspaceGrantId, permissionMode }) {
  const body = { task, permission_mode: permissionMode };
  if (workspaceGrantId) body.workspace_grant_id = workspaceGrantId;
  else body.workspace = workspace || ".";
  return request(`/api/runs/${encodeURIComponent(runId)}/continue`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function stopRun(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" });
}

export function undoChangeset(runId, changesetSequence) {
  return request(
    `/api/runs/${encodeURIComponent(runId)}/changesets/${encodeURIComponent(changesetSequence)}/undo`,
    { method: "POST" },
  );
}

export function resolveApproval(runId, approvalId, decision) {
  return request(
    `/api/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      method: "POST",
      body: JSON.stringify({ decision }),
    },
  );
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
