import { connectRunEvents, createRun, getRun, listRuns, stopRun } from "./api.js";
import { renderWorkspace } from "./render.js";
import {
  addEvent,
  selectRun,
  setConnectionState,
  setRuns,
  setSelectedPanel,
  state,
  subscribe,
  upsertRun,
} from "./store.js";

const elements = {
  connection: document.querySelector("#connection-status"),
  sessionList: document.querySelector("#session-list"),
  sessionEmpty: document.querySelector("#session-empty"),
  taskForm: document.querySelector("#task-form"),
  taskInput: document.querySelector("#task-input"),
  workspaceInput: document.querySelector("#workspace-input"),
  submitButton: document.querySelector("#submit-task"),
  stopButton: document.querySelector("#stop-run"),
  refreshButton: document.querySelector("#refresh-runs"),
  notice: document.querySelector("#app-notice"),
  runStatus: document.querySelector("#run-status"),
  conversation: document.querySelector("#conversation-panel"),
  conversationEmpty: document.querySelector("#conversation-empty"),
  evidenceTab: document.querySelector("#evidence-tab"),
  changesTab: document.querySelector("#changes-tab"),
  evidencePanel: document.querySelector("#evidence-panel"),
  changesPanel: document.querySelector("#changes-panel"),
  timeline: document.querySelector("#activity-timeline"),
};

let closeEventStream = null;

subscribe((snapshot) =>
  renderWorkspace(elements, snapshot, { onSelectRun: activateRun }),
);

elements.taskForm.addEventListener("submit", submitTask);
elements.stopButton.addEventListener("click", stopActiveRun);
elements.refreshButton.addEventListener("click", refreshRuns);
elements.evidenceTab.addEventListener("click", () => setSelectedPanel("evidence"));
elements.changesTab.addEventListener("click", () => setSelectedPanel("changes"));

await boot();

async function boot() {
  setConnectionState("connecting");
  try {
    const runs = await listRuns();
    setRuns(runs);
    setConnectionState("idle");
    if (state.activeRunId) connectToRun(state.activeRunId);
  } catch (error) {
    showNotice(error.message, true);
    setConnectionState("error");
  }
}

async function submitTask(event) {
  event.preventDefault();
  const task = elements.taskInput.value.trim();
  const workspace = elements.workspaceInput.value.trim() || ".";
  if (!task) return;
  setBusy(true);
  hideNotice();
  try {
    const run = await createRun({ task, workspace });
    upsertRun(run);
    selectRun(run.id);
    elements.taskInput.value = "";
    connectToRun(run.id);
  } catch (error) {
    showNotice(error.message, true);
    setConnectionState("error");
  } finally {
    setBusy(false);
  }
}

async function stopActiveRun() {
  if (!state.activeRunId) return;
  elements.stopButton.disabled = true;
  hideNotice();
  try {
    const run = await stopRun(state.activeRunId);
    upsertRun(run);
    closeStream();
    setConnectionState("idle");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function refreshRuns() {
  hideNotice();
  try {
    setRuns(await listRuns());
  } catch (error) {
    showNotice(error.message, true);
  }
}

function activateRun(runId) {
  if (state.activeRunId === runId && closeEventStream) return;
  selectRun(runId);
  connectToRun(runId);
}

function connectToRun(runId) {
  closeStream();
  setConnectionState("connecting");
  closeEventStream = connectRunEvents(runId, {
    onState(connectionState, detail) {
      setConnectionState(connectionState);
      if (detail) showNotice(detail, true);
    },
    async onEvent(storedEvent) {
      addEvent(runId, storedEvent);
      if (storedEvent.event.kind === "run_finished") {
        closeStream();
        setConnectionState("idle");
        try {
          upsertRun(await getRun(runId));
        } catch (error) {
          showNotice(error.message, true);
        }
      }
    },
  });
}

function closeStream() {
  if (closeEventStream) closeEventStream();
  closeEventStream = null;
}

function setBusy(busy) {
  elements.submitButton.disabled = busy;
  elements.taskInput.disabled = busy;
  elements.workspaceInput.disabled = busy;
}

function showNotice(message, isError = false) {
  elements.notice.textContent = message;
  elements.notice.className = `notice${isError ? " error" : ""}`;
  elements.notice.hidden = false;
}

function hideNotice() {
  elements.notice.hidden = true;
  elements.notice.textContent = "";
}
