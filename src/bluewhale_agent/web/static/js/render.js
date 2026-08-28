const ACTIVE_STATUSES = new Set(["initializing", "running", "waiting_approval", "verifying"]);

export function renderWorkspace(elements, snapshot, callbacks) {
  const run = snapshot.runs.find((item) => item.id === snapshot.activeRunId) || null;
  const events = snapshot.events.get(snapshot.activeRunId) || [];
  renderConnection(elements, snapshot.connectionState);
  renderSessions(elements, snapshot.runs, snapshot.activeRunId, callbacks.onSelectRun);
  renderRunHeader(elements, run);
  renderConversation(elements, run, events, callbacks.onResolveApproval);
  renderWorkDetails(elements, events);
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

function renderSessions(elements, runs, activeRunId, onSelectRun) {
  elements.sessionList.replaceChildren();
  elements.sessionEmpty.hidden = runs.length > 0;
  for (const run of runs.slice().reverse()) {
    const item = document.createElement("li");
    const button = element(
      "button",
      `session-button${run.id === activeRunId ? " active" : ""}`,
    );
    button.type = "button";
    button.addEventListener("click", () => onSelectRun(run.id));

    const copy = element("span", "session-copy");
    copy.append(
      element("strong", "", run.task),
      element("small", "", statusLabel(run.status)),
    );
    const status = element("span", `status-dot ${run.status}`);
    status.setAttribute("aria-label", `状态：${statusLabel(run.status)}`);
    button.append(copy, status);
    item.append(button);
    elements.sessionList.append(item);
  }
}

function renderRunHeader(elements, run) {
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
  const active = ACTIVE_STATUSES.has(run.status);
  elements.stopButton.hidden = !active;
  elements.submitButton.hidden = active;
}

function renderConversation(elements, run, events, onResolveApproval) {
  elements.conversation.replaceChildren();
  elements.conversationEmpty.hidden = Boolean(run);
  if (!run) return;

  const userMessage = element("article", "message user-message");
  userMessage.append(element("p", "", run.task));
  elements.conversation.append(userMessage);

  for (const stored of events) {
    const { kind, payload } = stored.event;
    if (kind === "model_response" && payload.content) {
      const message = element("article", "message assistant-message");
      message.append(avatar(), element("p", "message-copy", payload.content));
      elements.conversation.append(message);
    } else if (kind === "approval_requested") {
      elements.conversation.append(approvalCard(stored, events, onResolveApproval));
    } else if (
      kind === "observation_received" &&
      payload.observation?.status !== "success"
    ) {
      elements.conversation.append(errorMessage(payload.observation));
    } else if (kind === "run_finished") {
      elements.conversation.append(resultStrip(payload, events));
    }
  }
  const scroller = elements.conversation.closest(".conversation-scroll");
  scroller.scrollTop = scroller.scrollHeight;
}

function avatar() {
  const node = element("span", "assistant-avatar", "B");
  node.setAttribute("aria-hidden", "true");
  return node;
}

function approvalCard(stored, events, onResolveApproval) {
  const approval = stored.event.payload.approval;
  const resolution = events
    .filter((candidate) => candidate.event.kind === "approval_resolved")
    .find((candidate) => candidate.event.payload.approval?.id === approval.id);
  const status = resolution?.event.payload.approval?.status || approval.status;
  const pending = status === "pending";
  const card = element("article", `approval-card ${status}`);
  const heading = element("div", "approval-heading");
  heading.append(
    element("span", "approval-icon", "!"),
    element("div", "approval-title", `允许 ${humanToolLabel(approval.action.tool_name)}？`),
    element("span", "approval-status", approvalStatus(status)),
  );
  card.append(heading, element("p", "approval-reason", approval.reason));
  if (approval.impact_paths.length) {
    card.append(element("p", "approval-impact", `将影响：${approval.impact_paths.join("、")}`));
  }
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
  deny.disabled = !pending;
  approve.disabled = !pending;

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

function errorMessage(observation) {
  const message = element("article", "message system-message error");
  message.append(
    element("strong", "", "这一步没有完成"),
    element("p", "", observation.summary || "工具执行失败。"),
  );
  return message;
}

function resultStrip(payload, events) {
  const completed = payload.status === "completed";
  const changedFiles = changedFileCount(events);
  const strip = element("article", `result-strip ${completed ? "success" : "error"}`);
  strip.append(
    element("span", "result-icon", completed ? "✓" : "!"),
    element("strong", "", completed ? "任务已完成" : stopReasonLabel(payload.stop_reason)),
  );
  const facts = [];
  if (payload.verified === true) facts.push("验证已通过");
  if (payload.verified === false) facts.push("验证未通过");
  if (changedFiles) facts.push(`修改 ${changedFiles} 个文件`);
  if (facts.length) strip.append(element("span", "result-facts", facts.join(" · ")));
  return strip;
}

function renderWorkDetails(elements, events) {
  elements.workDetails.replaceChildren();
  const actions = events.filter((stored) => stored.event.kind === "action_requested");
  const verification = events.findLast(
    (stored) => stored.event.kind === "verification_finished",
  );
  if (!actions.length && !verification) {
    elements.workDetails.hidden = true;
    return;
  }
  elements.workDetails.hidden = false;
  const observations = new Map(
    events
      .filter((stored) => stored.event.kind === "observation_received")
      .map((stored) => [stored.event.payload.observation?.action_id, stored]),
  );
  const wrapper = document.createElement("details");
  wrapper.className = "work-disclosure";
  wrapper.append(workSummary(actions, events, verification));
  const list = element("ol", "work-list");
  for (const stored of actions) {
    list.append(workStep(stored, observations.get(stored.event.payload.action?.id)));
  }
  if (verification) list.append(verificationStep(verification));
  wrapper.append(list);
  elements.workDetails.append(wrapper);
}

function workSummary(actions, events, verification) {
  const summary = element("summary", "work-summary");
  const pieces = [`${actions.length} 步`];
  const files = changedFileCount(events);
  if (files) pieces.push(`${files} 个文件`);
  if (verification) pieces.push(verification.event.payload.outcome?.passed ? "验证通过" : "验证未通过");
  summary.append(
    element("span", "disclosure-chevron", "›"),
    element("strong", "", "工作过程"),
    element("span", "work-summary-meta", pieces.join(" · ")),
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

function changedFileCount(events) {
  return new Set(
    events
      .filter((stored) => stored.event.kind === "observation_received")
      .map((stored) => stored.event.payload.observation?.metadata?.path)
      .filter(Boolean),
  ).size;
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
