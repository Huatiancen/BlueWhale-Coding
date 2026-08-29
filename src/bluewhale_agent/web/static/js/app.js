import {
  connectRunEvents,
  continueRun,
  createRun,
  getRun,
  getRunFile,
  listRuns,
  resolveApproval,
  stopRun,
} from "./api.js";
import {
  activateDesktopHistoryWorkspace,
  clearDesktopApiKey,
  detectDesktopBridge,
  getDesktopSecretState,
  getDesktopWorkspaceState,
  saveDesktopApiKey,
  selectDesktopWorkspace,
} from "./desktop.js";
import { renderArtifactInspector } from "./artifact-view.js";
import { shouldSubmitComposer } from "./composer-keyboard.js";
import { homePrompt } from "./home-prompt.js";
import { setupPanelResizer } from "./panel-resize.js";
import { renderWorkspace } from "./render.js";
import { createStreamGuard } from "./stream-guard.js";
import { shouldCloseRunStream } from "./stream-lifecycle.js";
import { refreshActiveTurnDurations } from "./turn-timing.js";
import {
  addEvent,
  selectRun,
  setConnectionState,
  setPermissionMode,
  setRuns,
  state,
  subscribe,
  toggleProjectCollapsed,
  upsertRun,
} from "./store.js";

const ACTIVE_RUN_STATUSES = new Set([
  "initializing",
  "running",
  "waiting_approval",
  "verifying",
]);

const elements = {
  connection: document.querySelector("#connection-status"),
  sessionList: document.querySelector("#session-list"),
  sessionEmpty: document.querySelector("#session-empty"),
  newTask: document.querySelector("#new-task"),
  taskForm: document.querySelector("#task-form"),
  taskInput: document.querySelector("#task-input"),
  workspaceInput: document.querySelector("#workspace-input"),
  workspaceField: document.querySelector(".workspace-field"),
  desktopControls: document.querySelector("#desktop-controls"),
  desktopProject: document.querySelector("#desktop-project"),
  openProject: document.querySelector("#open-project"),
  homeTitle: document.querySelector("#home-title"),
  homeSubtitle: document.querySelector("#home-subtitle"),
  projectName: document.querySelector("#project-name"),
  projectPath: document.querySelector("#project-path"),
  openModelSettings: document.querySelector("#open-model-settings"),
  modelSettings: document.querySelector("#model-settings"),
  closeModelSettings: document.querySelector("#close-model-settings"),
  apiKeyForm: document.querySelector("#api-key-form"),
  apiKeyInput: document.querySelector("#api-key-input"),
  apiKeyStatus: document.querySelector("#api-key-status"),
  clearApiKey: document.querySelector("#clear-api-key"),
  submitButton: document.querySelector("#submit-task"),
  stopButton: document.querySelector("#stop-run"),
  refreshButton: document.querySelector("#refresh-runs"),
  notice: document.querySelector("#app-notice"),
  runTitle: document.querySelector("#active-run-title"),
  runStatus: document.querySelector("#run-status"),
  conversation: document.querySelector("#conversation-panel"),
  conversationEmpty: document.querySelector("#conversation-empty"),
  approvalDock: document.querySelector("#approval-dock"),
  inspector: document.querySelector("#artifact-inspector"),
  inspectorTitle: document.querySelector("#inspector-title"),
  inspectorToolbar: document.querySelector("#inspector-toolbar"),
  inspectorContent: document.querySelector("#inspector-content"),
  closeInspector: document.querySelector("#close-inspector"),
  sidebar: document.querySelector(".sidebar"),
  sidebarResizer: document.querySelector("#sidebar-resizer"),
  inspectorResizer: document.querySelector("#inspector-resizer"),
  permissionTrigger: document.querySelector("#permission-trigger"),
  permissionLabel: document.querySelector("#permission-label"),
  permissionMenu: document.querySelector("#permission-menu"),
  permissionOptions: [...document.querySelectorAll("[data-permission-mode]")],
};

let closeEventStream = null;
let desktopBridge = null;
let workspaceGrantId = null;
let workspacePath = null;
let busy = false;
let composerIsComposing = false;
let selectedArtifact = null;
const streamGuard = createStreamGuard();
let sidebarSize = 248;
let inspectorSize = Math.round(window.innerWidth * 0.46);

setupPanelResizer({
  handle: elements.sidebarResizer,
  getSize: () => sidebarSize,
  setSize: (size) => {
    sidebarSize = size;
    document.documentElement.style.setProperty("--sidebar-width", `${size}px`);
  },
  sizeFromPointer: (event) => event.clientX,
  min: 190,
  max: 420,
  growKey: "ArrowRight",
});

setupPanelResizer({
  handle: elements.inspectorResizer,
  getSize: () => inspectorSize,
  setSize: (size) => {
    inspectorSize = size;
    document.documentElement.style.setProperty("--inspector-width", `${size}px`);
  },
  sizeFromPointer: (event) => window.innerWidth - event.clientX,
  min: 320,
  max: () => Math.max(320, window.innerWidth - sidebarSize - 420),
  growKey: "ArrowLeft",
});

subscribe((snapshot) => {
  renderWorkspace(elements, snapshot, {
    onSelectRun: activateRun,
    onResolveApproval: submitApproval,
    onCopyError: (message) => showNotice(message, true),
    onToggleProject: toggleProjectCollapsed,
    onSelectArtifact: openArtifact,
  });
  updateControls();
  renderPermissionControl(snapshot.permissionMode);
});

elements.taskForm.addEventListener("submit", submitTask);
elements.newTask.addEventListener("click", startNewTask);
elements.stopButton.addEventListener("click", stopActiveRun);
elements.refreshButton.addEventListener("click", refreshRuns);
elements.openProject.addEventListener("click", openDesktopProject);
elements.desktopProject.addEventListener("click", openDesktopProject);
elements.openModelSettings.addEventListener("click", showModelSettings);
elements.closeModelSettings.addEventListener("click", () => elements.modelSettings.close());
elements.apiKeyForm.addEventListener("submit", saveApiKey);
elements.clearApiKey.addEventListener("click", clearApiKey);
elements.taskInput.addEventListener("input", resizeComposer);
elements.taskInput.addEventListener("keydown", submitWithShortcut);
elements.taskInput.addEventListener("compositionstart", () => {
  composerIsComposing = true;
});
elements.taskInput.addEventListener("compositionend", () => {
  composerIsComposing = false;
});
elements.permissionTrigger.addEventListener("click", togglePermissionMenu);
for (const option of elements.permissionOptions) {
  option.addEventListener("click", () => choosePermissionMode(option.dataset.permissionMode));
}
document.addEventListener("click", closePermissionMenuFromOutside);
document.addEventListener("keydown", closePermissionMenuWithEscape);

await boot();
window.setInterval(() => refreshActiveTurnDurations(document), 1000);

async function boot() {
  setConnectionState("connecting");
  try {
    await initializeDesktop();
    const runs = await listRuns();
    setRuns(runs);
    setConnectionState("idle");
  } catch (error) {
    showNotice(error.message, true);
    setConnectionState("error");
  }
}

async function submitTask(event) {
  event.preventDefault();
  const task = elements.taskInput.value.trim();
  const workspace = elements.workspaceInput.value.trim() || ".";
  const selectedRun = state.runs.find((item) => item.id === state.activeRunId);
  if (!task) return;
  if (desktopBridge && selectedRun?.continuable) {
    try {
      await ensureRunWorkspace(selectedRun);
    } catch (error) {
      showNotice(error.message, true);
      return;
    }
  }
  if (desktopBridge && !workspaceGrantId) {
    showNotice("请先打开一个项目。", true);
    return;
  }
  setBusy(true);
  hideNotice();
  try {
    const request = {
      task,
      workspace,
      workspaceGrantId,
      permissionMode: state.permissionMode,
    };
    const run = selectedRun?.continuable
      ? await continueRun(selectedRun.id, request)
      : await createRun(request);
    upsertRun(run);
    selectRun(run.id);
    elements.taskInput.value = "";
    resizeComposer();
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
  if (!window.confirm("确定要停止当前任务吗？")) return;
  elements.stopButton.disabled = true;
  hideNotice();
  setConnectionState("stopping");
  try {
    const run = await stopRun(state.activeRunId);
    upsertRun(run);
    closeStream();
    setConnectionState("idle");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function submitApproval(runId, approvalId, decision) {
  hideNotice();
  try {
    await resolveApproval(runId, approvalId, decision);
    return true;
  } catch (error) {
    showNotice(error.message, true);
    return false;
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

function startNewTask() {
  closeStream();
  closeArtifact();
  selectRun(null);
  setConnectionState("idle");
  hideNotice();
  elements.taskInput.focus();
}

async function activateRun(runId) {
  const alreadyConnected = state.activeRunId === runId && closeEventStream;
  if (!alreadyConnected) {
    closeArtifact();
    selectRun(runId);
    connectToRun(runId);
  }
  const run = state.runs.find((item) => item.id === runId);
  try {
    await ensureRunWorkspace(run);
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function openArtifact(file) {
  selectedArtifact = { ...file };
  renderArtifactInspector(elements, selectedArtifact, { onClose: closeArtifact });
  try {
    const current = await getRunFile(state.activeRunId, file.path);
    if (selectedArtifact?.path !== file.path) return;
    selectedArtifact = { ...selectedArtifact, currentContent: current.content };
    renderArtifactInspector(elements, selectedArtifact, { onClose: closeArtifact });
  } catch (error) {
    if (!file.after) showNotice(error.message, true);
  }
}

function closeArtifact() {
  selectedArtifact = null;
  renderArtifactInspector(elements, null, { onClose: closeArtifact });
}

function connectToRun(runId) {
  closeStream();
  const isCurrentStream = streamGuard.begin();
  setConnectionState("connecting");
  const run = state.runs.find((item) => item.id === runId);
  closeEventStream = connectRunEvents(runId, {
    async onState(connectionState, detail) {
      if (!isCurrentStream()) return;
      if (connectionState === "reconnecting") {
        if (run?.historical) {
          closeStream();
          setConnectionState("idle");
          return;
        }
        try {
          const refreshed = await getRun(runId);
          if (!isCurrentStream()) return;
          upsertRun(refreshed);
          if (shouldCloseRunStream(run, refreshed)) {
            closeStream();
            setConnectionState("idle");
            return;
          }
        } catch (error) {
          if (!isCurrentStream()) return;
          showNotice(error.message, true);
        }
      }
      if (!isCurrentStream()) {
        return;
      }
      setConnectionState(connectionState);
      if (detail) showNotice(detail, true);
    },
    async onEvent(storedEvent) {
      if (!isCurrentStream()) return;
      addEvent(runId, storedEvent);
      if (storedEvent.event.kind === "run_finished") {
        if (run?.historical) return;
        try {
          const refreshed = await getRun(runId);
          if (!isCurrentStream()) return;
          upsertRun(refreshed);
          updateControls();
        } catch (error) {
          if (!isCurrentStream()) return;
          showNotice(error.message, true);
        }
      }
    },
  });
}

function closeStream() {
  streamGuard.invalidate();
  if (closeEventStream) closeEventStream();
  closeEventStream = null;
}

function setBusy(isBusy) {
  busy = isBusy;
  elements.submitButton.disabled = isBusy || Boolean(desktopBridge && !workspaceGrantId);
  elements.taskInput.disabled = isBusy;
  elements.workspaceInput.disabled = isBusy;
  window.requestAnimationFrame(updateControls);
}

async function initializeDesktop() {
  desktopBridge = await detectDesktopBridge();
  if (!desktopBridge) return;
  document.body.dataset.runtime = "desktop";
  elements.desktopControls.hidden = false;
  elements.desktopProject.hidden = false;
  elements.openModelSettings.hidden = false;
  elements.workspaceField.hidden = true;
  const workspace = await getDesktopWorkspaceState(desktopBridge);
  if (workspace.configured) applyWorkspace(workspace);
  await refreshSecretState();
  updateControls();
}

async function openDesktopProject() {
  hideNotice();
  try {
    const result = await selectDesktopWorkspace(desktopBridge);
    if (!result.cancelled) {
      applyWorkspace(result);
      await refreshRuns();
      showNotice(`已授权项目：${result.display_name}`);
    }
  } catch (error) {
    showNotice(error.message, true);
  }
  updateControls();
}

function applyWorkspace(workspace) {
  workspaceGrantId = workspace.grant_id;
  workspacePath = workspace.display_path;
  elements.projectName.textContent = workspace.display_name;
  elements.projectPath.textContent = workspace.display_path;
  updateHomePrompt(workspace.display_name);
}

function updateHomePrompt(workspaceName = null) {
  const prompt = homePrompt(workspaceName);
  elements.homeTitle.textContent = prompt.title;
  elements.homeSubtitle.textContent = prompt.subtitle;
}

async function showModelSettings() {
  await refreshSecretState();
  elements.modelSettings.showModal();
  elements.apiKeyInput.focus();
}

async function refreshSecretState() {
  if (!desktopBridge) return;
  try {
    const result = await getDesktopSecretState(desktopBridge);
    elements.apiKeyStatus.textContent = result.configured ? "已安全配置" : "尚未配置";
    elements.apiKeyStatus.dataset.configured = String(result.configured);
  } catch (error) {
    elements.apiKeyStatus.textContent = error.message;
    elements.apiKeyStatus.dataset.configured = "error";
  }
}

async function saveApiKey(event) {
  event.preventDefault();
  const value = elements.apiKeyInput.value;
  try {
    await saveDesktopApiKey(desktopBridge, value);
    showNotice("DeepSeek API Key 已保存到 macOS 钥匙串。");
    await refreshSecretState();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    elements.apiKeyInput.value = "";
  }
}

async function clearApiKey() {
  try {
    await clearDesktopApiKey(desktopBridge);
    showNotice("已清除 macOS 钥匙串中的 DeepSeek API Key。");
    await refreshSecretState();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    elements.apiKeyInput.value = "";
  }
}

function updateControls() {
  const active = state.runs.some(
    (run) => !run.historical && ACTIVE_RUN_STATUSES.has(run.status),
  );
  const selectedRun = state.runs.find((run) => run.id === state.activeRunId);
  const needsWorkspace = Boolean(
    desktopBridge && !workspaceGrantId && !selectedRun?.continuable,
  );
  elements.openProject.disabled = busy || active;
  elements.newTask.disabled = busy || active;
  elements.desktopProject.disabled = busy || active;
  elements.submitButton.disabled =
    busy || active || needsWorkspace;
  elements.taskInput.disabled = busy || active;
  elements.workspaceInput.disabled = busy || active;
  elements.permissionTrigger.disabled = busy || active;
  if (busy || active) closePermissionMenu();
}

async function ensureRunWorkspace(run) {
  if (!desktopBridge || !run?.continuable) return;
  if (workspaceGrantId && workspacePath === run.workspace) return;
  const workspace = await activateDesktopHistoryWorkspace(desktopBridge, run.id);
  applyWorkspace(workspace);
}

function togglePermissionMenu(event) {
  event.stopPropagation();
  if (elements.permissionTrigger.disabled) return;
  const opening = elements.permissionMenu.hidden;
  elements.permissionMenu.hidden = !opening;
  elements.permissionTrigger.setAttribute("aria-expanded", String(opening));
}

function choosePermissionMode(permissionMode) {
  if (!permissionMode) return;
  setPermissionMode(permissionMode);
  closePermissionMenu();
}

function renderPermissionControl(permissionMode) {
  const labels = { ask: "请求批准", balanced: "帮我批准", full: "完全访问权限" };
  elements.permissionLabel.textContent = labels[permissionMode];
  elements.permissionTrigger.dataset.permissionMode = permissionMode;
  for (const option of elements.permissionOptions) {
    option.setAttribute("aria-checked", String(option.dataset.permissionMode === permissionMode));
  }
}

function closePermissionMenu() {
  elements.permissionMenu.hidden = true;
  elements.permissionTrigger.setAttribute("aria-expanded", "false");
}

function closePermissionMenuFromOutside(event) {
  if (!elements.permissionMenu.hidden && !event.target.closest(".permission-control")) {
    closePermissionMenu();
  }
}

function closePermissionMenuWithEscape(event) {
  if (event.key === "Escape" && !elements.permissionMenu.hidden) {
    closePermissionMenu();
    elements.permissionTrigger.focus();
  }
}

function resizeComposer() {
  elements.taskInput.style.height = "auto";
  elements.taskInput.style.height = `${Math.min(elements.taskInput.scrollHeight, 180)}px`;
}

function submitWithShortcut(event) {
  if (!shouldSubmitComposer(event, composerIsComposing)) return;
  event.preventDefault();
  elements.taskForm.requestSubmit();
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
