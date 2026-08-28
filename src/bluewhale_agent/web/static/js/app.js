import {
  connectRunEvents,
  createRun,
  getRun,
  listRuns,
  resolveApproval,
  stopRun,
} from "./api.js";
import {
  clearDesktopApiKey,
  detectDesktopBridge,
  getDesktopSecretState,
  getDesktopWorkspaceState,
  saveDesktopApiKey,
  selectDesktopWorkspace,
} from "./desktop.js";
import { renderWorkspace } from "./render.js";
import {
  addEvent,
  selectRun,
  setConnectionState,
  setPermissionMode,
  setRuns,
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
  workspaceField: document.querySelector(".workspace-field"),
  desktopControls: document.querySelector("#desktop-controls"),
  desktopProject: document.querySelector("#desktop-project"),
  openProject: document.querySelector("#open-project"),
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
  workDetails: document.querySelector("#work-details"),
  permissionTrigger: document.querySelector("#permission-trigger"),
  permissionLabel: document.querySelector("#permission-label"),
  permissionMenu: document.querySelector("#permission-menu"),
  permissionOptions: [...document.querySelectorAll("[data-permission-mode]")],
};

let closeEventStream = null;
let desktopBridge = null;
let workspaceGrantId = null;
let busy = false;

subscribe((snapshot) => {
  renderWorkspace(elements, snapshot, {
    onSelectRun: activateRun,
    onResolveApproval: submitApproval,
  });
  updateControls();
  renderPermissionControl(snapshot.permissionMode);
});

elements.taskForm.addEventListener("submit", submitTask);
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
elements.permissionTrigger.addEventListener("click", togglePermissionMenu);
for (const option of elements.permissionOptions) {
  option.addEventListener("click", () => choosePermissionMode(option.dataset.permissionMode));
}
document.addEventListener("click", closePermissionMenuFromOutside);
document.addEventListener("keydown", closePermissionMenuWithEscape);

await boot();

async function boot() {
  setConnectionState("connecting");
  try {
    await initializeDesktop();
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
  if (desktopBridge && !workspaceGrantId) {
    showNotice("请先打开一个项目。", true);
    return;
  }
  setBusy(true);
  hideNotice();
  try {
    const run = await createRun({
      task,
      workspace,
      workspaceGrantId,
      permissionMode: state.permissionMode,
    });
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
    showNotice(decision === "approve" ? "已批准本次操作。" : "已拒绝本次操作。");
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
          updateControls();
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
      showNotice(`已授权项目：${result.display_name}`);
    }
  } catch (error) {
    showNotice(error.message, true);
  }
  updateControls();
}

function applyWorkspace(workspace) {
  workspaceGrantId = workspace.grant_id;
  elements.projectName.textContent = workspace.display_name;
  elements.projectPath.textContent = workspace.display_path;
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
  const active = state.runs.some((run) =>
    ["initializing", "running", "waiting_approval", "verifying"].includes(run.status),
  );
  elements.openProject.disabled = busy || active;
  elements.desktopProject.disabled = busy || active;
  elements.submitButton.disabled =
    busy || active || Boolean(desktopBridge && !workspaceGrantId);
  elements.taskInput.disabled = busy || active;
  elements.workspaceInput.disabled = busy || active;
  elements.permissionTrigger.disabled = busy || active;
  if (busy || active) closePermissionMenu();
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
  if (event.key !== "Enter" || (!event.metaKey && !event.ctrlKey)) return;
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
