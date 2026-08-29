import { conversationTimeline } from "./conversation-turns.js";
import { findPendingApproval } from "./event-view.js";
import { renderMarkdown } from "./markdown.js";
import { createMessageCopyButton } from "./message-copy.js";
import { groupRunsByProject } from "./project-groups.js";
import { formatTurnDuration, turnDurationMs } from "./turn-timing.js";

const ACTIVE_STATUSES = new Set(["initializing", "running", "waiting_approval", "verifying"]);

export function renderWorkspace(elements, snapshot, callbacks) {
  const run = snapshot.runs.find((item) => item.id === snapshot.activeRunId) || null;
  const events = snapshot.events.get(snapshot.activeRunId) || [];
  renderConnection(elements, snapshot.connectionState);
  renderSessions(
    elements,
    snapshot.runs,
    snapshot.activeRunId,
    snapshot.collapsedProjects,
    callbacks.onSelectRun,
    callbacks.onToggleProject,
  );
  renderRunHeader(elements, run);
  renderConversation(
    elements,
    run,
    events,
    callbacks.onCopyError,
    callbacks.onSelectArtifact,
  );
  renderApprovalDock(elements, events, run, callbacks.onResolveApproval);
}

function renderConnection(elements, connectionState) {
  const labels = {
    reconnecting: "连接中断，正在恢复",
    stopping: "正在停止任务",
    error: "连接发生错误",
  };
  const visible = Object.hasOwn(labels, connectionState);
  elements.connection.textContent = labels[connectionState] || "";
  const cluster = elements.connection.parentElement;
  cluster.hidden = !visible;
  cluster.dataset.state = connectionState;
}

function renderSessions(
  elements,
  runs,
  activeRunId,
  collapsedProjects = new Set(),
  onSelectRun,
  onToggleProject,
) {
  elements.sessionList.replaceChildren();
  elements.sessionEmpty.hidden = runs.length > 0;
  for (const project of groupRunsByProject(runs)) {
    const item = document.createElement("li");
    item.className = "project-group";
    const containsActive = project.runs.some((run) => run.id === activeRunId);
    const expanded = containsActive || !collapsedProjects.has(project.key);
    const projectButton = element("button", "history-project-button");
    projectButton.type = "button";
    projectButton.setAttribute("aria-expanded", String(expanded));
    projectButton.addEventListener("click", () => onToggleProject(project.key));
    projectButton.append(
      folderIcon(),
      element("span", "project-name", project.name),
    );
    if (!project.available) {
      projectButton.append(element("span", "project-unavailable", "不可用"));
    }
    const chevron = element("span", "project-chevron", "›");
    chevron.setAttribute("aria-hidden", "true");
    projectButton.append(chevron);

    const taskList = element("ol", "project-task-list");
    taskList.hidden = !expanded;
    for (const run of project.runs) {
      const taskItem = document.createElement("li");
      const taskButton = element(
        "button",
        `session-button${run.id === activeRunId ? " active" : ""}`,
        run.task,
      );
      taskButton.type = "button";
      taskButton.title = run.task;
      if (run.id === activeRunId) taskButton.setAttribute("aria-current", "true");
      taskButton.addEventListener("click", () => onSelectRun(run.id));
      taskItem.append(taskButton);
      taskList.append(taskItem);
    }
    item.append(projectButton, taskList);
    elements.sessionList.append(item);
  }
}

function folderIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("project-folder-icon");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute(
    "d",
    "M3.5 6.5h6l2 2h9v8.75A2.25 2.25 0 0 1 18.25 19.5H5.75A2.25 2.25 0 0 1 3.5 17.25V6.5Z",
  );
  svg.append(path);
  return svg;
}

function renderRunHeader(elements, run) {
  elements.runTitle.parentElement.hidden = !run;
  elements.runTitle.textContent = run?.task || "新任务";
  if (!run) {
    elements.runStatus.hidden = true;
    elements.stopButton.hidden = true;
    elements.submitButton.hidden = false;
    return;
  }
  elements.runStatus.hidden = false;
  elements.runStatus.textContent = statusLabel(run.status);
  elements.runStatus.className = `run-status ${run.status}`;
  const active = !run.historical && ACTIVE_STATUSES.has(run.status);
  elements.stopButton.hidden = !active;
  elements.submitButton.hidden = active;
}

function renderConversation(elements, run, events, onCopyError, onSelectArtifact) {
  elements.conversation.replaceChildren();
  elements.conversationEmpty.hidden = Boolean(run);
  if (!run) return;

  for (const entry of conversationTimeline(run, events)) {
    if (entry.kind === "user") {
      const message = element("article", "message user-message");
      message.append(
        element("p", "", entry.content),
        createMessageCopyButton(entry.content, { onError: onCopyError }),
      );
      elements.conversation.append(message);
    } else if (entry.kind === "work") {
      elements.conversation.append(createWorkDetails(entry));
    } else if (entry.kind === "assistant") {
      const message = element("article", "message assistant-message");
      const markdown = renderMarkdown(entry.content);
      markdown.classList.add("message-copy");
      message.append(
        markdown,
        createMessageCopyButton(entry.content, { onError: onCopyError }),
      );
      elements.conversation.append(message);
    } else if (entry.kind === "changeset") {
      elements.conversation.append(changeSetCard(entry.payload, onSelectArtifact));
    }
  }
  const scroller = elements.conversation.closest(".conversation-scroll");
  scroller.scrollTop = scroller.scrollHeight;
}

function changeSetCard(payload, onSelectArtifact) {
  const files = payload.files || [];
  const card = element("section", "changeset-card");
  const heading = element("div", "changeset-heading");
  const icon = element("span", "changeset-icon", "▣");
  icon.setAttribute("aria-hidden", "true");
  const summary = element("div", "changeset-summary");
  const totals = element("span", "changeset-totals");
  if (!payload.legacy) {
    totals.append(
      element("span", "changeset-total additions", `+${payload.additions || 0}`),
      element("span", "changeset-total deletions", `-${payload.deletions || 0}`),
    );
  } else {
    totals.append(element("span", "legacy-change-note", "历史记录仅可查看当前文件"));
  }
  summary.append(
    element("strong", "", `${payload.legacy ? "涉及" : "已编辑"} ${files.length} 个文件`),
    totals,
  );
  const undo = element("button", "changeset-undo", "撤销");
  undo.type = "button";
  undo.disabled = true;
  undo.title = "撤销功能即将支持";
  heading.append(
    icon,
    summary,
    undo,
  );
  card.append(heading);
  const list = element("div", "changeset-files");
  for (const file of files) {
    const button = element("button", "changeset-file");
    button.type = "button";
    button.append(element("span", "changeset-path", file.path));
    if (!payload.legacy) {
      button.append(
        element("span", "additions", `+${file.additions || 0}`),
        element("span", "deletions", `-${file.deletions || 0}`),
      );
    }
    button.append(element("span", "file-chevron", "›"));
    button.addEventListener("click", () => onSelectArtifact(file));
    list.append(button);
  }
  card.append(list);
  return card;
}

function renderApprovalDock(elements, events, run, onResolveApproval) {
  elements.approvalDock.replaceChildren();
  if (run?.historical) {
    elements.approvalDock.hidden = true;
    return;
  }
  const stored = findPendingApproval(events);
  elements.approvalDock.hidden = !stored;
  if (stored) elements.approvalDock.append(approvalCard(stored, onResolveApproval));
}

function approvalCard(stored, onResolveApproval) {
  const approval = stored.event.payload.approval;
  const card = element("article", "approval-card pending");
  const heading = element("div", "approval-heading");
  heading.append(
    element("span", "approval-icon", "!"),
    element("div", "approval-title", `允许${humanToolLabel(approval.action?.tool_name)}？`),
  );
  card.append(heading);
  const context = element("div", "approval-context");
  context.append(element("span", "approval-risk-label", "需要你的确认"));
  const command = approval.action?.arguments?.command;
  if (typeof command === "string" && command.trim()) {
    context.append(element("code", "approval-command-preview", command.trim()));
  }
  context.append(element("p", "approval-reason", approval.reason));
  if (approval.impact_paths?.length) {
    context.append(element("p", "approval-impact", `将影响：${approval.impact_paths.join("、")}`));
  }
  card.append(context);
  const technical = document.createElement("details");
  technical.className = "technical-details";
  technical.append(
    element("summary", "", "技术详情"),
    element("pre", "", safeJson(approval.action.arguments)),
  );
  card.append(technical);

  const actions = element("div", "approval-actions");
  const deny = approvalButton("拒绝", "secondary", "deny");
  const approve = approvalButton("允许一次", "primary", "approve");

  async function decide(decision) {
    deny.disabled = true;
    approve.disabled = true;
    if (!(await onResolveApproval(approval.run_id, approval.id, decision))) {
      deny.disabled = false;
      approve.disabled = false;
    }
  }

  deny.addEventListener("click", () => decide("deny"));
  approve.addEventListener("click", () => decide("approve"));
  actions.append(deny, approve);
  card.append(actions);
  return card;
}

function approvalButton(label, variant, decision) {
  const button = element("button", `button ${variant}`, label);
  button.type = "button";
  button.dataset.decision = decision;
  return button;
}

function createWorkDetails(work) {
  const events = work.events || [];
  const actions = events.filter((stored) => stored.event.kind === "action_requested");
  const actionIds = new Set(
    actions.map((stored) => stored.event.payload.action?.id).filter(Boolean),
  );
  const verification = events.findLast(
    (stored) => stored.event.kind === "verification_finished",
  );
  const unmatchedFailures = events.filter((stored) => {
    if (stored.event.kind !== "observation_received") return false;
    const observation = stored.event.payload.observation;
    return observation?.status !== "success" && !actionIds.has(observation?.action_id);
  });
  const failedRun = events.findLast(
    (stored) =>
      stored.event.kind === "run_finished" &&
      stored.event.payload.status !== "completed",
  );
  const section = element("section", "turn-work work-details");
  section.setAttribute("aria-label", "工作过程");
  const observations = new Map(
    events
      .filter((stored) => stored.event.kind === "observation_received")
      .map((stored) => [stored.event.payload.observation?.action_id, stored]),
  );
  const wrapper = document.createElement("details");
  wrapper.className = "work-disclosure";
  wrapper.append(workSummary(work));
  const list = element("ol", "work-list");
  for (const narration of work.modelNarration || []) {
    list.append(modelProcessStep(narration));
  }
  for (const stored of actions) {
    list.append(workStep(stored, observations.get(stored.event.payload.action?.id)));
  }
  for (const stored of unmatchedFailures) list.append(observationStep(stored));
  if (verification) list.append(verificationStep(verification));
  if (failedRun) list.append(runOutcomeStep(failedRun));
  if (
    !work.modelNarration?.length &&
    !actions.length &&
    !unmatchedFailures.length &&
    !verification &&
    !failedRun
  ) {
    list.append(element("li", "work-empty", "本轮未调用本地工具"));
  }
  wrapper.append(list);
  section.append(wrapper);
  return section;
}

function modelProcessStep(content) {
  const item = element("li", "work-step model-process-step");
  item.append(
    element("span", "step-dot"),
    element("span", "step-title", content),
    element("span", "step-state", "分析"),
  );
  return item;
}

function workSummary(work) {
  const summary = element("summary", "work-summary");
  const duration = element(
    "span",
    "work-duration",
    formatTurnDuration(turnDurationMs(work), work.active),
  );
  duration.dataset.active = String(work.active);
  duration.dataset.startedAt = work.startedAt || "";
  summary.append(
    duration,
    element("span", "disclosure-chevron", "›"),
  );
  return summary;
}

function workStep(stored, observationStored) {
  const action = stored.event.payload.action || {};
  const observation = observationStored?.event.payload.observation;
  const item = element("li", `work-step ${observation?.status || "pending"}`);
  const details = document.createElement("details");
  const summary = element("summary", "step-summary");
  summary.append(
    element("span", "step-dot"),
    element("span", "step-title", humanToolSummary(action)),
    element("span", "step-state", observationStatus(observation?.status)),
  );
  const body = element("div", "step-body");
  if (observation?.summary) body.append(element("p", "", observation.summary));
  body.append(element("pre", "", safeJson(action.arguments || {})));
  if (observation?.content) body.append(element("pre", "", observation.content));
  details.append(summary, body);
  item.append(details);
  return item;
}

function observationStep(stored) {
  const observation = stored.event.payload.observation || {};
  const item = element("li", `work-step ${observation.status || "error"}`);
  const details = document.createElement("details");
  const summary = element("summary", "step-summary");
  summary.append(
    element("span", "step-dot"),
    element("span", "step-title", observation.summary || "工具执行失败"),
    element("span", "step-state", observationStatus(observation.status)),
  );
  const body = element("div", "step-body");
  if (observation.content) body.append(element("pre", "", observation.content));
  if (observation.metadata && Object.keys(observation.metadata).length) {
    body.append(element("pre", "", safeJson(observation.metadata)));
  }
  if (body.childElementCount) details.append(summary, body);
  else details.append(summary);
  item.append(details);
  return item;
}

function runOutcomeStep(stored) {
  const payload = stored.event.payload || {};
  const item = element("li", "work-step error");
  item.append(
    element("span", "step-dot"),
    element("span", "step-title", stopReasonLabel(payload.stop_reason)),
    element("span", "step-state", payload.status === "stopped" ? "已停止" : "未完成"),
  );
  return item;
}

function verificationStep(stored) {
  const outcome = stored.event.payload.outcome || {};
  const item = element("li", `work-step ${outcome.passed ? "success" : "error"}`);
  item.append(
    element("span", "step-dot"),
    element("span", "step-title", outcome.passed ? "本地验证通过" : "本地验证未通过"),
    element("span", "step-state", `${outcome.rounds || 0} 轮`),
  );
  return item;
}

function humanToolSummary(action) {
  const args = action.arguments || {};
  const target = args.path || args.pattern || args.command || "";
  return [humanToolLabel(action.tool_name), target].filter(Boolean).join(" ");
}

function humanToolLabel(toolName) {
  const labels = {
    list_files: "查看文件",
    read_file: "读取文件",
    search_text: "搜索代码",
    write_file: "写入文件",
    apply_patch: "修改文件",
    get_diff: "检查变更",
    run_command: "运行命令",
  };
  return labels[toolName] || "执行操作";
}

function statusLabel(status) {
  const labels = {
    initializing: "正在准备",
    running: "正在工作",
    waiting_approval: "等待你确认",
    verifying: "正在验证",
    completed: "已完成",
    failed: "未完成",
    stopped: "已停止",
  };
  return labels[status] || status;
}

function stopReasonLabel(reason) {
  const labels = {
    user_stopped: "任务已停止",
    app_interrupted: "应用退出，任务已中断",
    permission_denied: "操作未获授权",
    api_error: "模型服务暂时不可用",
    tool_error: "执行过程遇到错误",
    verification_failed: "修改未通过验证",
    step_limit: "已达执行步数上限",
    time_limit: "已达执行时间上限",
  };
  return labels[reason] || "任务未完成";
}

function approvalStatus(status) {
  const labels = {
    pending: "等待确认",
    approved: "已允许",
    denied: "已拒绝",
    expired: "已超时",
    cancelled: "已取消",
  };
  return labels[status] || status;
}

function observationStatus(status) {
  const labels = { success: "完成", error: "失败", denied: "未授权" };
  return labels[status] || "进行中";
}

function element(tagName, className = "", text = "") {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

function safeJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return "[无法显示技术详情]";
  }
}
