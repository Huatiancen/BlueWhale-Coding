const CATEGORY = Object.freeze({
  PLAN: "PLAN",
  MODEL: "MODEL",
  TOOL: "TOOL",
  EDIT: "EDIT",
  TEST: "TEST",
  ERROR: "ERROR",
  DONE: "DONE",
});

export function renderWorkspace(elements, snapshot, callbacks) {
  const run = snapshot.runs.find((item) => item.id === snapshot.activeRunId) || null;
  const events = snapshot.events.get(snapshot.activeRunId) || [];
  renderConnection(elements, snapshot.connectionState);
  renderSessions(elements, snapshot.runs, snapshot.activeRunId, callbacks.onSelectRun);
  renderRunStatus(elements, run);
  renderConversation(elements, events, callbacks.onResolveApproval);
  renderInspector(elements, events, snapshot.selectedPanel);
  renderTimeline(elements, events);
}

function renderConnection(elements, connectionState) {
  const labels = {
    idle: "本地服务就绪",
    connecting: "正在连接事件流",
    connected: "实时轨迹已连接",
    reconnecting: "连接中断，正在恢复",
    stopping: "正在安全停止任务",
    error: "连接发生错误",
  };
  elements.connection.textContent = labels[connectionState] || connectionState;
  elements.connection.parentElement.dataset.state = connectionState;
}

function renderSessions(elements, runs, activeRunId, onSelectRun) {
  elements.sessionList.replaceChildren();
  elements.sessionEmpty.hidden = runs.length > 0;
  runs
    .slice()
    .reverse()
    .forEach((run, index) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = `session-button${run.id === activeRunId ? " active" : ""}`;
      button.addEventListener("click", () => onSelectRun(run.id));

      const code = element("span", "session-code", String(runs.length - index).padStart(2, "0"));
      const copy = element("span", "session-copy");
      copy.append(element("strong", "", run.task), element("small", "", shortId(run.id)));
      const status = element("span", `status-dot ${run.status}`);
      status.setAttribute("aria-label", `状态：${run.status}`);
      button.append(code, copy, status);
      item.append(button);
      elements.sessionList.append(item);
    });
}

function renderRunStatus(elements, run) {
  const status = run?.status || "neutral";
  elements.runStatus.className = `status-pill ${status}`;
  elements.runStatus.textContent = run ? statusLabel(status) : "未运行";
  elements.stopButton.disabled =
    !run || !["initializing", "running", "waiting_approval", "verifying"].includes(status);
}

function renderConversation(elements, events, onResolveApproval) {
  elements.conversation.replaceChildren();
  const visible = events.filter((stored) =>
    [
      "model_response",
      "action_requested",
      "approval_requested",
      "observation_received",
      "verification_finished",
    ].includes(stored.event.kind),
  );
  elements.conversationEmpty.hidden = visible.length > 0;
  for (const stored of visible) {
    if (stored.event.kind === "approval_requested") {
      elements.conversation.append(
        approvalCard(stored, events, onResolveApproval),
      );
      continue;
    }
    const category = classify(stored);
    const card = element("article", `message-card ${category.toLowerCase()}`);
    const meta = element("div", "message-meta");
    meta.append(element("span", "", category), element("time", "", formatTime(stored.recorded_at)));
    const body = element("p", "message-body", eventDescription(stored));
    card.append(meta, body);
    elements.conversation.append(card);
  }
  const scroller = elements.conversation.parentElement;
  scroller.scrollTop = scroller.scrollHeight;
}

function approvalCard(stored, events, onResolveApproval) {
  const approval = stored.event.payload.approval;
  const resolution = events
    .filter((candidate) => candidate.event.kind === "approval_resolved")
    .find((candidate) => candidate.event.payload.approval?.id === approval.id);
  const status = resolution?.event.payload.approval?.status || approval.status;
  const pending = status === "pending";
  const card = element("article", `approval-card ${status}`);
  const heading = document.createElement("header");
  const title = element("div", "");
  title.append(
    element("span", "event-badge", "APPROVAL"),
    element("h3", "", `允许执行 ${approval.action.tool_name}？`),
  );
  heading.append(title, element("span", `approval-status ${status}`, approvalStatus(status)));

  const reason = element("p", "approval-reason", approval.reason);
  const argumentsBlock = element("pre", "approval-arguments", safeJson(approval.action.arguments));
  const impact = element(
    "p",
    "approval-impact",
    approval.impact_paths.length
      ? `影响路径：${approval.impact_paths.join("、")}`
      : "影响路径：未声明具体文件路径",
  );
  const actions = element("div", "approval-actions");
  const deny = approvalButton("拒绝", "deny danger", "deny");
  const approve = approvalButton("批准一次", "approve", "approve");
  deny.disabled = !pending;
  approve.disabled = !pending;

  async function decide(decision) {
    deny.disabled = true;
    approve.disabled = true;
    const accepted = await onResolveApproval(
      approval.run_id,
      approval.id,
      decision,
    );
    if (!accepted) {
      deny.disabled = false;
      approve.disabled = false;
    }
  }

  deny.addEventListener("click", () => decide("deny"));
  approve.addEventListener("click", () => decide("approve"));
  actions.append(deny, approve);
  card.append(heading, reason, argumentsBlock, impact, actions);
  return card;
}

function approvalButton(label, className, decision) {
  const button = element("button", `approval-button ${className}`, label);
  button.type = "button";
  button.dataset.decision = decision;
  return button;
}

function renderInspector(elements, events, selectedPanel) {
  const evidenceSelected = selectedPanel === "evidence";
  elements.evidencePanel.hidden = !evidenceSelected;
  elements.changesPanel.hidden = evidenceSelected;
  elements.evidenceTab.classList.toggle("active", evidenceSelected);
  elements.changesTab.classList.toggle("active", !evidenceSelected);
  elements.evidenceTab.setAttribute("aria-selected", String(evidenceSelected));
  elements.changesTab.setAttribute("aria-selected", String(!evidenceSelected));

  elements.evidencePanel.replaceChildren();
  const evidence = events.filter((stored) =>
    ["observation_received", "verification_finished"].includes(stored.event.kind),
  );
  if (!evidence.length) {
    elements.evidencePanel.append(emptyCopy("尚无证据", "工具结果与验证结论会在此归档。"));
  }
  for (const stored of evidence) {
    const observation = stored.event.payload.observation;
    const success = observation ? observation.status === "success" : stored.event.payload.outcome?.passed;
    const card = element("article", `evidence-card ${success ? "success" : "error"}`);
    const header = document.createElement("header");
    header.append(
      element("strong", "", stored.event.kind === "verification_finished" ? "Verification Gate" : "Tool evidence"),
      element("span", "hash", `#${stored.sequence}`),
    );
    card.append(header, element("p", "evidence-body", eventDescription(stored)));
    elements.evidencePanel.append(card);
  }

  elements.changesPanel.replaceChildren();
  const changes = events.filter((stored) => {
    const metadata = stored.event.payload.observation?.metadata;
    return stored.event.kind === "observation_received" && metadata?.path && metadata?.after_sha256;
  });
  if (!changes.length) {
    elements.changesPanel.append(emptyCopy("尚无变更", "文件修改后会显示路径与内容指纹。"));
  }
  for (const stored of changes) {
    const metadata = stored.event.payload.observation.metadata;
    const card = element("article", "change-card");
    const header = document.createElement("header");
    header.append(element("strong", "", metadata.path), element("span", "hash", shortHash(metadata.after_sha256)));
    card.append(header, element("p", "change-body", stored.event.payload.observation.summary));
    elements.changesPanel.append(card);
  }
}

function renderTimeline(elements, events) {
  elements.timeline.replaceChildren();
  for (const stored of events) {
    const category = classify(stored);
    const item = element("li", `timeline-item ${category.toLowerCase()}`);
    item.append(
      element("span", "event-badge", category),
      element("p", "timeline-title", eventTitle(stored)),
      element("time", "timeline-time", formatTime(stored.recorded_at)),
    );
    elements.timeline.append(item);
  }
  elements.timeline.scrollLeft = elements.timeline.scrollWidth;
}

function classify(stored) {
  const { kind, payload } = stored.event;
  if (kind === "model_response") return CATEGORY.MODEL;
  if (kind === "action_requested") return CATEGORY.TOOL;
  if (kind === "approval_requested") return CATEGORY.PLAN;
  if (kind === "approval_resolved") {
    return payload.approval?.status === "approved" ? CATEGORY.DONE : CATEGORY.ERROR;
  }
  if (kind === "verification_finished") return payload.outcome?.passed ? CATEGORY.DONE : CATEGORY.TEST;
  if (kind === "run_finished") return payload.status === "completed" ? CATEGORY.DONE : CATEGORY.ERROR;
  if (kind === "observation_received") {
    if (payload.observation?.status !== "success") return CATEGORY.ERROR;
    if (payload.verification) return CATEGORY.TEST;
    if (payload.observation?.metadata?.after_sha256) return CATEGORY.EDIT;
    return CATEGORY.TOOL;
  }
  return CATEGORY.PLAN;
}

function eventTitle(stored) {
  const titles = {
    run_started: "任务已进入执行队列",
    state_changed: `状态切换为 ${stored.event.payload.status || "unknown"}`,
    model_response: "模型完成一次推理",
    action_requested: `请求工具 ${stored.event.payload.action?.tool_name || "unknown"}`,
    approval_requested: `等待审批 ${stored.event.payload.approval?.action?.tool_name || "unknown"}`,
    approval_resolved: `审批结果：${stored.event.payload.approval?.status || "unknown"}`,
    observation_received: stored.event.payload.observation?.summary || "收到工具结果",
    verification_finished: "验证门禁完成",
    run_finished: `任务以 ${stored.event.payload.stop_reason || "unknown"} 结束`,
  };
  return titles[stored.event.kind] || stored.event.kind;
}

function approvalStatus(status) {
  const labels = {
    pending: "等待决定",
    approved: "已批准",
    denied: "已拒绝",
    expired: "已超时拒绝",
    cancelled: "已取消",
  };
  return labels[status] || status;
}

function eventDescription(stored) {
  const payload = stored.event.payload;
  if (stored.event.kind === "model_response") return payload.content || "模型请求继续调用工具。";
  if (stored.event.kind === "action_requested") {
    const action = payload.action || {};
    return `${action.tool_name || "tool"}\n${safeJson(action.arguments || {})}`;
  }
  if (stored.event.kind === "observation_received") {
    const observation = payload.observation || {};
    return [observation.summary, observation.content].filter(Boolean).join("\n") || "工具已返回。";
  }
  if (stored.event.kind === "verification_finished") {
    const outcome = payload.outcome || {};
    return `结论：${outcome.stop_reason || "unknown"} · ${outcome.rounds || 0} 轮 · ${outcome.repair_attempts || 0} 次修复`;
  }
  return eventTitle(stored);
}

function emptyCopy(title, description) {
  const wrapper = element("div", "empty-state compact");
  wrapper.append(element("span", "empty-glyph", "◌"), element("p", "", title), element("small", "", description));
  return wrapper;
}

function element(tagName, className = "", text = "") {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

function statusLabel(status) {
  const labels = {
    initializing: "初始化",
    running: "执行中",
    waiting_approval: "等待审批",
    verifying: "验证中",
    completed: "已完成",
    failed: "失败",
    stopped: "已停止",
  };
  return labels[status] || status;
}

function shortId(value) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-5)}` : value;
}

function shortHash(value) {
  return value ? `${value.slice(0, 9)}…` : "—";
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function safeJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return "[无法序列化的参数]";
  }
}
