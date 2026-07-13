const state = {
  snapshot: null,
  loading: false,
  lastSuccessAt: 0,
  chartHours: 6,
  detailTaskId: null,
};

const numberFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });
const percentFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const exactFormatter = new Intl.NumberFormat("zh-CN");

function byId(id) {
  return document.getElementById(id);
}

function formatTokens(value) {
  const amount = Number(value || 0);
  if (amount >= 100_000_000) return `${numberFormatter.format(amount / 100_000_000)}亿`;
  if (amount >= 10_000) return `${numberFormatter.format(amount / 10_000)}万`;
  return exactFormatter.format(amount);
}

function formatClock(epochSeconds) {
  if (!epochSeconds) return "--";
  return new Date(epochSeconds * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function formatCountdown(epochSeconds) {
  if (!epochSeconds) return "未报告";
  const seconds = Math.max(0, epochSeconds - Date.now() / 1000);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}天${hours}小时`;
  if (hours > 0) return `${hours}小时${minutes}分`;
  return `${minutes}分钟`;
}

function formatAge(epochSeconds) {
  if (!epochSeconds) return "时间未知";
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}小时前`;
  return `${Math.floor(seconds / 86400)}天前`;
}

function formatDateTime(epochSeconds) {
  if (!epochSeconds) return "--";
  return new Date(epochSeconds * 1000).toLocaleString("zh-CN", { hour12: false });
}

function formatDuration(startEpoch, endEpoch = Date.now() / 1000) {
  if (!startEpoch) return "--";
  const seconds = Math.max(0, Number(endEpoch || Date.now() / 1000) - Number(startEpoch));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}小时${minutes}分`;
  return `${Math.max(1, minutes)}分钟`;
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function windowLabel(windowData) {
  if (!windowData) return "未报告";
  if (windowData.kind === "short") return `${numberFormatter.format(windowData.window_minutes / 60)}小时窗口`;
  if (windowData.kind === "weekly") return `${numberFormatter.format(windowData.window_minutes / 1440)}天窗口`;
  return `${windowData.window_minutes}分钟窗口`;
}

function updateQuotaCard(kind, prefix) {
  const windowData = state.snapshot?.quota_windows?.find((item) => item.kind === kind);
  const card = byId(`${prefix}-window`);
  const gauge = byId(`${prefix}-gauge`);
  if (!windowData) {
    card.classList.add("unavailable");
    gauge.style.setProperty("--value", "0");
    byId(`${prefix}-remaining`).textContent = "--";
    byId(`${prefix}-used`).textContent = "未报告";
    byId(`${prefix}-reset`).textContent = "未报告";
    byId(`${prefix}-window-name`).textContent = prefix === "short" ? "短周期未报告" : "周窗口未报告";
    return;
  }
  card.classList.remove("unavailable");
  const remaining = Math.max(0, Math.min(100, windowData.remaining_percent));
  gauge.style.setProperty("--value", remaining.toFixed(2));
  gauge.setAttribute("aria-label", `${windowLabel(windowData)}剩余 ${remaining}%`);
  byId(`${prefix}-remaining`).textContent = numberFormatter.format(remaining);
  byId(`${prefix}-used`).textContent = `${numberFormatter.format(windowData.used_percent)}%`;
  byId(`${prefix}-reset`).textContent = formatCountdown(windowData.resets_at);
  byId(`${prefix}-window-name`).textContent = windowLabel(windowData);
}

function statusLabel(status) {
  return {
    running: "运行中",
    waiting: "等待确认",
    paused: "已暂停",
    completed: "已完成",
    unavailable: "不可用",
    idle: "空闲",
  }[status] || status;
}

function priorityLabel(value) {
  return { 1: "低", 2: "较低", 3: "普通", 4: "较高", 5: "最高" }[value] || "普通";
}

function showToast(message, error = false) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.className = `toast ${error ? "error" : "success"}`;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 2200);
}

function createTaskRow(task) {
  const row = document.createElement("article");
  row.className = "task-row";
  row.dataset.taskId = task.id;
  row.dataset.status = task.status;

  const primary = document.createElement("div");
  primary.className = "task-primary";
  const dot = document.createElement("i");
  dot.className = `status-dot ${task.status}`;
  dot.setAttribute("aria-label", statusLabel(task.status));
  const text = document.createElement("div");
  text.className = "task-text";
  const title = document.createElement("button");
  title.type = "button";
  title.className = "task-title task-title-button";
  const displayName = task.preference?.display_name?.trim();
  title.textContent = displayName || task.title || `未命名任务 ${task.id.slice(-6)}`;
  title.title = title.textContent;
  title.addEventListener("click", () => openTaskDetail(task.id));

  const meta = document.createElement("div");
  meta.className = "task-meta";
  const alias = document.createElement("input");
  alias.className = "task-alias";
  alias.type = "text";
  alias.maxLength = 32;
  alias.value = displayName || "";
  alias.placeholder = `监控名称 · ${task.id.slice(-6)}`;
  alias.setAttribute("aria-label", "本地监控名称");
  alias.title = "仅修改本机监控名称";
  alias.addEventListener("change", async () => {
    await saveControl(alias, task.id, { display_name: alias.value.trim() }, "名称已保存");
  });
  alias.addEventListener("keydown", (event) => {
    if (event.key === "Enter") alias.blur();
  });
  const metaText = document.createElement("span");
  const burn = Number(task.burn_rate_tokens_per_minute || 0);
  metaText.textContent = [
    statusLabel(task.status),
    task.model || "模型未报告",
    formatAge(task.updated_at),
    burn ? `${formatTokens(burn)}/分` : "速度校准中",
  ].join(" · ");
  meta.append(alias, metaText);
  text.append(title, meta);
  primary.append(dot, text);

  const tokenMetric = document.createElement("div");
  tokenMetric.className = "task-metric token-metric";
  const tokenValue = Number(task.tokens?.total_tokens || 0);
  const turnValue = Number(task.turn_tokens || 0);
  tokenMetric.innerHTML = `<strong>${formatTokens(tokenValue)}</strong><span>本次 ${formatTokens(turnValue)}</span>`;
  tokenMetric.title = `累计 ${exactFormatter.format(tokenValue)} Token；本次 ${exactFormatter.format(turnValue)} Token`;

  const budget = task.budget || {};
  const budgetControl = document.createElement("div");
  budgetControl.className = "budget-control";
  const budgetStatus = document.createElement("div");
  budgetStatus.className = "budget-status";
  const actual = budget.cap_percent;
  const automatic = budget.automatic_percent;
  const manual = task.preference?.manual_cap_percent;
  const activeBudget = ["running", "waiting"].includes(task.status);
  const available = Number(state.snapshot?.budget_plan?.available_percent || 0);
  const allocationShare = actual != null && available > 0 ? Math.min(100, actual / available * 100) : 0;
  const actualText = actual == null ? "待运行计算" : `建议上限 ${percentFormatter.format(actual)}%`;
  const automaticText = actual == null
    ? (manual == null ? "自动模式" : `手动目标 ${percentFormatter.format(manual)}%`)
    : (manual == null
      ? `自动 · 占安全池 ${numberFormatter.format(allocationShare)}%`
      : `手动目标 · 自动值 ${percentFormatter.format(automatic || 0)}%`);
  budgetStatus.innerHTML = `<strong>${actualText}</strong><span>${automaticText}</span>`;
  const allocationTrack = document.createElement("div");
  allocationTrack.className = `allocation-track ${activeBudget ? "active" : ""}`;
  const allocationFill = document.createElement("i");
  allocationFill.style.width = `${allocationShare}%`;
  allocationTrack.append(allocationFill);
  budgetStatus.append(allocationTrack);

  const budgetEdit = document.createElement("div");
  budgetEdit.className = "budget-edit";
  const budgetInput = document.createElement("input");
  budgetInput.type = "number";
  budgetInput.inputMode = "decimal";
  budgetInput.min = "0";
  budgetInput.max = "100";
  budgetInput.step = "0.1";
  budgetInput.value = task.preference?.manual_cap_percent ?? "";
  budgetInput.placeholder = "自动";
  budgetInput.setAttribute("aria-label", `${title.textContent}手动建议上限百分比`);
  budgetInput.title = "留空使用自动建议；该数值只用于提醒，不会中断 Codex";
  budgetInput.addEventListener("change", async () => {
    const raw = budgetInput.value.trim();
    const value = raw === "" ? null : Number(raw);
    if (value != null && (!Number.isFinite(value) || value < 0 || value > 100)) {
      showToast("建议上限必须在 0% 到 100% 之间", true);
      return;
    }
    await saveControl(budgetInput, task.id, { manual_cap_percent: value }, value == null ? "已恢复自动建议" : "手动建议已保存");
  });
  budgetInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") budgetInput.blur();
  });
  const percent = document.createElement("span");
  percent.textContent = "%";
  const autoButton = document.createElement("button");
  autoButton.type = "button";
  autoButton.textContent = "自动";
  autoButton.disabled = task.preference?.manual_cap_percent == null;
  autoButton.title = "清除手动值，恢复系统自动建议";
  autoButton.addEventListener("click", async () => {
    budgetInput.value = "";
    await saveControl(autoButton, task.id, { manual_cap_percent: null }, "已恢复自动建议");
  });
  budgetEdit.append(budgetInput, percent, autoButton);
  budgetControl.append(budgetStatus, budgetEdit);

  const priority = document.createElement("div");
  priority.className = "priority-control";
  const select = document.createElement("select");
  select.setAttribute("aria-label", `${title.textContent}优先级`);
  select.title = "优先级越高，系统自动预算权重越高；手动预算不受优先级影响";
  for (let value = 1; value <= 5; value += 1) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = `${value} · ${priorityLabel(value)}`;
    select.append(option);
  }
  select.value = String(task.preference?.priority || 3);
  select.addEventListener("change", async () => {
    await saveControl(select, task.id, { priority: Number(select.value) }, "优先级已保存");
  });
  priority.append(select);

  row.append(primary, tokenMetric, budgetControl, priority);
  return row;
}

function renderTasks() {
  const focused = document.activeElement;
  if (focused?.closest?.(".task-row") && ["INPUT", "SELECT", "BUTTON"].includes(focused.tagName)) return;
  const allTasks = [...(state.snapshot?.tasks || [])];
  const tasks = allTasks
    .sort((left, right) => Number(right.updated_at || 0) - Number(left.updated_at || 0))
    .slice(0, 5);
  byId("task-list").replaceChildren(...tasks.map(createTaskRow));
  byId("empty-state").hidden = tasks.length > 0;
  byId("task-total").textContent = String(allTasks.length);
}

function taskName(task) {
  return task.preference?.display_name?.trim() || task.title || `未命名任务 ${task.id.slice(-6)}`;
}

function detailMetric(label, value, hint = "") {
  const metric = createElement("div", "detail-metric");
  metric.append(createElement("span", "", label), createElement("strong", "", value));
  if (hint) metric.append(createElement("small", "", hint));
  return metric;
}

function detailField(label, value) {
  const field = createElement("div", "detail-field");
  field.append(createElement("dt", "", label), createElement("dd", "", value || "--"));
  return field;
}

function renderTaskDetail() {
  const task = (state.snapshot?.tasks || []).find((item) => item.id === state.detailTaskId);
  if (!task) return;
  byId("task-detail-title").textContent = taskName(task);
  const tokens = task.tokens || {};
  const budget = task.budget || {};
  const body = byId("task-detail-body");

  const summary = createElement("section", "detail-summary");
  summary.append(
    detailMetric("累计 Token", formatTokens(tokens.total_tokens), exactFormatter.format(tokens.total_tokens || 0)),
    detailMetric("本次 Token", formatTokens(task.turn_tokens), task.status === "running" ? "实时增加" : "最近一次"),
    detailMetric("消耗速度", task.burn_rate_tokens_per_minute ? `${formatTokens(task.burn_rate_tokens_per_minute)}/分` : "校准中"),
    detailMetric("运行时长", formatDuration(task.turn_started_at, task.turn_finished_at)),
  );

  const breakdown = createElement("section", "detail-section");
  breakdown.append(createElement("h3", "", "Token 分项"));
  const breakdownGrid = createElement("div", "token-breakdown");
  breakdownGrid.append(
    detailMetric("输入", formatTokens(tokens.input_tokens)),
    detailMetric("缓存输入", formatTokens(tokens.cached_input_tokens)),
    detailMetric("输出", formatTokens(tokens.output_tokens)),
    detailMetric("推理输出", formatTokens(tokens.reasoning_output_tokens)),
  );
  breakdown.append(breakdownGrid);

  const metadata = createElement("section", "detail-section");
  metadata.append(createElement("h3", "", "任务信息"));
  const fields = createElement("dl", "detail-fields");
  fields.append(
    detailField("状态", statusLabel(task.status)),
    detailField("模型", task.model || "未报告"),
    detailField("推理强度", task.reasoning_effort || "未报告"),
    detailField("来源", task.source),
    detailField("创建时间", formatDateTime(task.created_at)),
    detailField("最近更新", formatDateTime(task.updated_at)),
    detailField("本次开始", formatDateTime(task.turn_started_at)),
    detailField("工程目录", task.cwd),
  );
  metadata.append(fields);

  const budgetSection = createElement("section", "detail-section budget-detail");
  budgetSection.append(createElement("h3", "", "预算建议"));
  const budgetGrid = createElement("div", "budget-detail-grid");
  budgetGrid.append(
    detailMetric("当前建议上限", budget.cap_percent == null ? "待运行计算" : `${percentFormatter.format(budget.cap_percent)}%`),
    detailMetric("系统自动建议", budget.automatic_percent == null ? "待运行计算" : `${percentFormatter.format(budget.automatic_percent)}%`),
    detailMetric("手动目标", task.preference?.manual_cap_percent == null ? "自动" : `${percentFormatter.format(task.preference.manual_cap_percent)}%`),
    detailMetric("优先级", `${task.preference?.priority || 3} · ${priorityLabel(task.preference?.priority || 3)}`),
  );
  budgetSection.append(budgetGrid, createElement("p", "detail-note", "建议预算用于规划与提醒，不会自动暂停或中断 Codex 任务。"));
  body.replaceChildren(summary, breakdown, metadata, budgetSection);
}

function openTaskDetail(taskId) {
  state.detailTaskId = taskId;
  renderTaskDetail();
  const dialog = byId("task-detail-dialog");
  if (!dialog.open) dialog.showModal();
}

function taskMatchesStatus(task, filter) {
  if (filter === "active") return ["running", "waiting"].includes(task.status);
  if (filter === "completed") return task.status === "completed";
  if (filter === "idle") return ["idle", "paused"].includes(task.status);
  return true;
}

function renderAllTasks() {
  const query = byId("task-search").value.trim().toLocaleLowerCase("zh-CN");
  const filter = byId("task-status-filter").value;
  const tasks = [...(state.snapshot?.tasks || [])]
    .sort((left, right) => Number(right.updated_at || 0) - Number(left.updated_at || 0))
    .filter((task) => taskMatchesStatus(task, filter))
    .filter((task) => {
      if (!query) return true;
      return [taskName(task), task.title, task.model, task.cwd, task.id]
        .some((value) => String(value || "").toLocaleLowerCase("zh-CN").includes(query));
    });
  const rows = tasks.map((task) => {
    const button = createElement("button", "all-task-row");
    button.type = "button";
    button.append(
      createElement("span", "all-task-name", taskName(task)),
      createElement("span", `status-text ${task.status}`, statusLabel(task.status)),
      createElement("strong", "", formatTokens(task.tokens?.total_tokens)),
      createElement("span", "", formatTokens(task.turn_tokens)),
      createElement("span", "", formatAge(task.updated_at)),
    );
    button.title = task.title;
    button.addEventListener("click", () => {
      byId("all-tasks-dialog").close();
      openTaskDetail(task.id);
    });
    return button;
  });
  byId("filtered-task-count").textContent = `${tasks.length} 个任务`;
  byId("all-task-list").replaceChildren(...rows);
}

function openAllTasks() {
  renderAllTasks();
  const dialog = byId("all-tasks-dialog");
  if (!dialog.open) dialog.showModal();
}

function exportSnapshot() {
  if (!state.snapshot) return;
  const content = JSON.stringify(state.snapshot, null, 2);
  const blob = new Blob([content], { type: "application/json;charset=utf-8" });
  const link = document.createElement("a");
  const stamp = new Date().toISOString().replaceAll(":", "-").slice(0, 19);
  link.href = URL.createObjectURL(blob);
  link.download = `codex-token-snapshot-${stamp}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  showToast("实时快照已导出");
}

async function saveControl(control, taskId, patch, successMessage) {
  control.disabled = true;
  try {
    await updatePreference(taskId, patch);
    showToast(successMessage);
  } catch (error) {
    showToast(error instanceof Error ? error.message : "保存失败", true);
  } finally {
    control.disabled = false;
    control.blur();
  }
}

async function updatePreference(taskId, patch) {
  const response = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) throw new Error(`更新失败：${response.status}`);
  await fetchStatus();
}

function renderSummary() {
  const snapshot = state.snapshot || {};
  const tasks = snapshot.tasks || [];
  const running = tasks.filter((task) => task.status === "running");
  const runningTokens = running.reduce((sum, task) => sum + Number(task.tokens?.total_tokens || 0), 0);
  const burnRate = running.reduce((sum, task) => sum + Number(task.burn_rate_tokens_per_minute || 0), 0);
  const turnRows = snapshot.turn_display?.tasks || [];
  const turnTokens = turnRows.reduce((sum, task) => sum + Number(task.turn_tokens || 0), 0);
  const daily = snapshot.daily_usage || {};
  const plan = snapshot.budget_plan || {};

  byId("active-count").textContent = String(running.length);
  byId("running-tokens").textContent = formatTokens(runningTokens);
  byId("turn-tokens").textContent = formatTokens(turnTokens);
  byId("daily-tokens").textContent = formatTokens(daily.tokens);
  byId("daily-tokens").title = `距离今日刷新 ${formatCountdown(daily.resets_at)}`;
  byId("burn-rate").textContent = burnRate ? `${formatTokens(burnRate)}/分` : "校准中";
  byId("available-budget").textContent = `${percentFormatter.format(plan.available_percent || 0)}%`;
  byId("budget-source").textContent = {
    short_and_weekly: "双窗口约束",
    short: "短周期窗口",
    weekly_ration: "周额度折算",
    unavailable: "等待额度数据",
  }[plan.source] || plan.source || "--";
  byId("short-reserve").textContent = `${numberFormatter.format(plan.reserves?.short_percent ?? 10)}%`;
  byId("weekly-reserve").textContent = `${numberFormatter.format(plan.reserves?.weekly_percent ?? 15)}%`;
  byId("weekly-slots").textContent = plan.weekly_slots_remaining ? `${plan.weekly_slots_remaining}个` : "--";
  byId("data-source").textContent = snapshot.source || "--";
  const warning = byId("warning-text");
  const messages = snapshot.warnings || [];
  warning.hidden = messages.length === 0;
  warning.textContent = messages.join("；");
}

function drawChart() {
  const canvas = byId("quota-chart");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(140, rect.width);
  const height = Math.max(70, rect.height);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const padding = { top: 5, right: 3, bottom: 4, left: 3 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  context.lineWidth = 1;
  context.strokeStyle = "#e0e3e7";
  for (const value of [0, 50, 100]) {
    const y = padding.top + plotHeight * (1 - value / 100);
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
  }

  const history = state.snapshot?.quota_history || [];
  const now = Date.now() / 1000;
  const rangeSeconds = state.chartHours * 3600;
  const start = now - rangeSeconds;
  const series = [
    { points: history.filter((item) => item.observed_at >= start && item.window_minutes >= 240 && item.window_minutes <= 360), color: "#168a67" },
    { points: history.filter((item) => item.observed_at >= start && item.window_minutes >= 9000), color: "#0b57d0" },
  ];
  for (const item of series) {
    if (!item.points.length) continue;
    context.beginPath();
    context.lineWidth = 2;
    context.strokeStyle = item.color;
    item.points.forEach((point, index) => {
      const x = padding.left + plotWidth * Math.max(0, Math.min(1, (point.observed_at - start) / rangeSeconds));
      const y = padding.top + plotHeight * (1 - Math.max(0, Math.min(100, point.used_percent)) / 100);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  }
}

function render() {
  updateQuotaCard("short", "short");
  updateQuotaCard("weekly", "weekly");
  renderSummary();
  renderTasks();
  if (byId("task-detail-dialog").open) renderTaskDetail();
  if (byId("all-tasks-dialog").open && !document.activeElement?.closest("#all-tasks-dialog")) renderAllTasks();
  drawChart();
  const online = state.snapshot?.health === "ok";
  byId("live-dot").className = `live-dot ${online ? "online" : "error"}`;
  byId("connection-label").textContent = online ? "实时采集中" : "数据源异常";
  byId("updated-at").textContent = `${formatClock(state.snapshot?.generated_at)} 更新`;
}

function setChartRange(hours) {
  state.chartHours = hours;
  byId("chart-range-label").textContent = `最近 ${hours} 小时`;
  byId("chart-range-start").textContent = `${hours} 小时前`;
  document.querySelectorAll("[data-chart-hours]").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.chartHours) === hours);
  });
  drawChart();
}

async function fetchStatus() {
  if (state.loading) return;
  state.loading = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.snapshot = await response.json();
    state.lastSuccessAt = Date.now();
    render();
  } catch (error) {
    byId("live-dot").className = "live-dot error";
    byId("connection-label").textContent = "连接已中断";
    byId("updated-at").textContent = error instanceof Error ? error.message : "读取失败";
  } finally {
    state.loading = false;
  }
}

window.addEventListener("resize", () => {
  if (state.snapshot) drawChart();
});

byId("all-tasks-button").addEventListener("click", openAllTasks);
byId("recent-all-button").addEventListener("click", openAllTasks);
byId("export-button").addEventListener("click", exportSnapshot);
byId("task-detail-close").addEventListener("click", () => byId("task-detail-dialog").close());
byId("all-tasks-close").addEventListener("click", () => byId("all-tasks-dialog").close());
byId("task-search").addEventListener("input", renderAllTasks);
byId("task-status-filter").addEventListener("change", renderAllTasks);
document.querySelectorAll("[data-chart-hours]").forEach((button) => {
  button.addEventListener("click", () => setChartRange(Number(button.dataset.chartHours)));
});
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

setInterval(() => {
  byId("footer-clock").textContent = new Date().toLocaleString("zh-CN", { hour12: false });
  if (state.snapshot) {
    updateQuotaCard("short", "short");
    updateQuotaCard("weekly", "weekly");
  }
}, 1000);

fetchStatus();
setInterval(fetchStatus, 1000);
