const state = {
  snapshot: null,
  loading: false,
  lastSuccessAt: 0,
  chartHours: 6,
  detailTaskId: null,
  chartPointer: { visible: false, locked: false, ratio: 1 },
  chartFrame: 0,
};

const THEME_STORAGE_KEY = "codex-token-theme";
const CHART_CONTINUITY_GAP_SECONDS = 90 * 60;

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

function formatQuotaWait(freshness) {
  return freshness === "expired" ? "等待新周期上报" : "等待 Codex 上报";
}

function formatBudgetState(value) {
  return value === "calibrating" ? "校准中" : "等待额度";
}

function formatBudgetForecast(budget) {
  if (!budget) return "无活动预算";
  if (budget.forecast === "exhausts") {
    const minutes = Math.max(1, Math.ceil(Number(budget.seconds_remaining || 0) / 60));
    const duration = minutes >= 60 ? `${Math.floor(minutes / 60)}小时${minutes % 60}分` : `${minutes}分钟`;
    return `约${duration}耗尽`;
  }
  return {
    exhausted: "建议预算已用尽",
    waiting: "等待中",
    unknown_rate: "速度校准中",
    after_reset: "刷新前充足",
  }[budget.forecast] || formatBudgetState(budget.forecast);
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

function cssColor(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function applyTheme(theme, persist = true) {
  const nextTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  document.querySelector('meta[name="theme-color"]').content = nextTheme === "dark" ? "#101214" : "#f7f8fc";
  document.querySelectorAll("[data-theme-value]").forEach((button) => {
    const active = button.dataset.themeValue === nextTheme;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (persist) {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch (_error) {}
  }
  if (state.snapshot) scheduleChartDraw();
}

function storedTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) || document.documentElement.dataset.theme;
  } catch (_error) {
    return document.documentElement.dataset.theme;
  }
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
    card.classList.remove("stale");
    gauge.style.setProperty("--value", "0");
    byId(`${prefix}-remaining`).textContent = "--";
    byId(`${prefix}-remaining-label`).textContent = "% 剩余";
    byId(`${prefix}-used`).textContent = "未报告";
    byId(`${prefix}-reset`).textContent = "未报告";
    byId(`${prefix}-source`).textContent = "等待上报";
    byId(`${prefix}-window-name`).textContent = prefix === "short" ? "短周期未报告" : "周窗口未报告";
    return;
  }
  card.classList.remove("unavailable");
  card.classList.toggle("stale", Boolean(windowData.is_stale));
  const remaining = Math.max(0, Math.min(100, windowData.remaining_percent));
  gauge.style.setProperty("--value", remaining.toFixed(2));
  const reportedPrefix = windowData.is_stale ? "上次上报" : "当前上报";
  gauge.setAttribute("aria-label", `${windowLabel(windowData)}${reportedPrefix}剩余 ${remaining}%`);
  byId(`${prefix}-remaining`).textContent = numberFormatter.format(remaining);
  byId(`${prefix}-remaining-label`).textContent = windowData.is_stale ? "% 上次剩余" : "% 剩余";
  byId(`${prefix}-used`).textContent = windowData.is_stale
    ? `上次 ${numberFormatter.format(windowData.used_percent)}%`
    : `${numberFormatter.format(windowData.used_percent)}%`;
  byId(`${prefix}-reset`).textContent = windowData.is_stale
    ? "暂不可确认"
    : formatCountdown(windowData.resets_at);
  byId(`${prefix}-source`).textContent = windowData.is_stale
    ? formatQuotaWait(windowData.freshness)
    : "已同步";
  byId(`${prefix}-window-name`).textContent = windowLabel(windowData);
}

function updateUsageStreak() {
  const streak = state.snapshot?.usage_streak || {};
  const card = byId("usage-streak-card");
  const unavailable = streak.source === "unavailable";
  const days = Math.max(0, Number(streak.days || 0));
  const tokens = Math.max(0, Number(streak.tokens || 0));
  const currentDayTokens = Math.max(0, Number(streak.current_day_tokens || 0));
  card.classList.toggle("unavailable", unavailable);
  byId("usage-streak-days").textContent = numberFormatter.format(days);
  byId("usage-streak-total").textContent = formatTokens(tokens);
  byId("usage-streak-today").textContent = formatTokens(currentDayTokens);
  byId("usage-streak-source").textContent = unavailable ? "数据不可用" : "本地日志";
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

function createTaskBudgetStatus(task) {
  const budget = task.budget?.token;
  const budgetStatus = createElement("div", "budget-status");
  const activeBudget = ["running", "waiting"].includes(task.status);
  const remaining = budget?.remaining_tokens;
  const used = budget?.window_used_tokens;
  const total = budget?.suggested_total_tokens;
  const usageShare = total > 0 ? Math.min(100, used / total * 100) : 0;
  const availableText = !activeBudget ? "无活动预算" : `可用估算 ${remaining == null ? formatBudgetState(budget?.forecast) : formatTokens(remaining)}`;
  const forecastText = formatBudgetForecast(budget);
  budgetStatus.append(createElement("strong", "", availableText));
  if (activeBudget) {
    budgetStatus.append(
      createElement("span", "", `五小时已用 ${used == null ? "--" : formatTokens(used)}`),
      createElement("span", `budget-forecast ${budget?.forecast === "exhausted" ? "exhausted" : ""}`, forecastText),
    );
  }
  budgetStatus.title = activeBudget
    ? `本地估算，非官方 Token 配额。五小时已用 ${used == null ? "未知" : exactFormatter.format(used)} Token；可用估算 ${remaining == null ? "校准中或额度未报告" : exactFormatter.format(remaining)} Token；${forecastText}${budget?.exhausts_at ? `（${formatDateTime(budget.exhausts_at)}）` : ""}`
    : "只为活动任务分配本地提醒预算";
  const allocationTrack = createElement("div", `allocation-track ${activeBudget ? "active" : ""}`);
  const allocationFill = createElement("i");
  allocationFill.style.width = `${usageShare}%`;
  allocationTrack.append(allocationFill);
  allocationTrack.title = "当前五小时已用 /（已用 + 可用估算）；非账户额度比例";
  allocationTrack.hidden = !activeBudget || remaining == null;
  budgetStatus.append(allocationTrack);
  return budgetStatus;
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
  tokenMetric.innerHTML = `<strong>${formatTokens(tokenValue)}</strong><span>本轮消耗 ${formatTokens(turnValue)}</span>`;
  tokenMetric.title = `任务累计 ${exactFormatter.format(tokenValue)} Token；本轮消耗 ${exactFormatter.format(turnValue)} Token`;

  const budgetControl = document.createElement("div");
  budgetControl.className = "budget-control";
  const budgetStatus = createTaskBudgetStatus(task);

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
  budgetInput.setAttribute("aria-label", `${title.textContent}手动估算容量百分比`);
  budgetInput.title = "本地估算五小时总容量的百分比，单任务最多 40%；不足时按可用池缩减。留空自动分配，仅提醒，不会中断 Codex";
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
  const allTasks = [...(state.snapshot?.tasks || [])];
  if (focused?.closest?.(".task-row") && ["INPUT", "SELECT", "BUTTON"].includes(focused.tagName)) {
    for (const row of byId("task-list").children) {
      const task = allTasks.find((item) => item.id === row.dataset.taskId);
      if (task) {
        row.querySelector(".budget-status").replaceWith(createTaskBudgetStatus(task));
        row.querySelector(".budget-edit button").disabled = task.preference?.manual_cap_percent == null;
      }
    }
    return;
  }
  const activeCount = allTasks.filter((task) => ["running", "waiting"].includes(task.status)).length;
  const tasks = allTasks
    .sort((left, right) => Number(["running", "waiting"].includes(right.status)) - Number(["running", "waiting"].includes(left.status)) || Number(right.updated_at || 0) - Number(left.updated_at || 0))
    .slice(0, Math.max(5, activeCount));
  byId("task-list").replaceChildren(...tasks.map(createTaskRow));
  byId("task-list").classList.toggle("many-active", tasks.length > 5);
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
  const budget = task.budget?.token;
  const body = byId("task-detail-body");

  const summary = createElement("section", "detail-summary");
  summary.append(
    detailMetric("任务累计", formatTokens(tokens.total_tokens), exactFormatter.format(tokens.total_tokens || 0)),
    detailMetric("本轮消耗", formatTokens(task.turn_tokens), task.status === "running" ? "实时增加" : "最近一轮"),
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
  budgetSection.append(createElement("h3", "", "五小时预算（本地估算）"));
  const budgetGrid = createElement("div", "budget-detail-grid");
  budgetGrid.append(
    detailMetric("可用预算估算", budget?.remaining_tokens == null ? (budget ? formatBudgetState(budget.forecast) : "无活动预算") : formatTokens(budget.remaining_tokens), budget?.remaining_tokens == null ? "" : `${exactFormatter.format(budget.remaining_tokens)} Token`),
    detailMetric("五小时已用", budget?.window_used_tokens == null ? "--" : formatTokens(budget.window_used_tokens), budget?.window_used_tokens == null ? "" : `${exactFormatter.format(budget.window_used_tokens)} Token`),
    detailMetric("预计耗尽", formatBudgetForecast(budget), budget?.exhausts_at ? formatDateTime(budget.exhausts_at) : ""),
    detailMetric("建议总量估算", budget?.suggested_total_tokens == null ? "--" : formatTokens(budget.suggested_total_tokens), "窗口已用 + 可用估算"),
    detailMetric("五小时窗口", formatDateTime(state.snapshot?.budget_plan?.token_budget?.started_at), `刷新 ${formatDateTime(state.snapshot?.budget_plan?.token_budget?.resets_at)}`),
    detailMetric("手动容量比例", task.preference?.manual_cap_percent == null ? "自动" : `${percentFormatter.format(task.preference.manual_cap_percent)}%`, budget?.mode === "manual_adjusted" ? "已按可用池缩减" : "相对本地估算容量，非官方配额"),
    detailMetric("优先级", `${task.preference?.priority || 3} · ${priorityLabel(task.preference?.priority || 3)}`),
  );
  budgetSection.append(budgetGrid, createElement("p", "detail-note", "基于账户额度变化与本地 Token 增量校准，非 Codex 官方 Token 配额。仅提醒，不会中断任务；预算与预测随活动任务和消耗速度变化。"));
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
  const running = tasks.filter((task) => ["running", "waiting"].includes(task.status));
  const runningTokens = running.reduce((sum, task) => sum + Number(task.tokens?.total_tokens || 0), 0);
  const burnRate = running.reduce((sum, task) => sum + Number(task.burn_rate_tokens_per_minute || 0), 0);
  const turnRows = snapshot.turn_display?.tasks || [];
  const turnTokens = turnRows.reduce((sum, task) => sum + Number(task.turn_tokens || 0), 0);
  const daily = snapshot.daily_usage || {};
  const plan = snapshot.budget_plan || {};
  const tokenPlan = plan.token_budget || {};

  byId("active-count").textContent = String(running.length);
  byId("running-tokens").textContent = formatTokens(runningTokens);
  byId("turn-tokens").textContent = formatTokens(turnTokens);
  byId("daily-tokens").textContent = formatTokens(daily.tokens);
  byId("daily-tokens").title = `距离今日刷新 ${formatCountdown(daily.resets_at)}`;
  byId("burn-rate").textContent = burnRate ? `${formatTokens(burnRate)}/分` : "校准中";
  byId("available-budget").textContent = tokenPlan.available_tokens == null
    ? formatBudgetState(tokenPlan.state)
    : formatTokens(tokenPlan.available_tokens);
  byId("available-budget").title = tokenPlan.available_tokens == null
    ? "需要有效的五小时额度和足够的本地校准样本；非官方 Token 配额"
    : `本地建议池估算 ${exactFormatter.format(tokenPlan.available_tokens)} Token；非官方 Token 配额`;
  byId("budget-source").textContent = tokenPlan.state === "ready" ? "本地样本估算" : formatBudgetState(tokenPlan.state);
  byId("short-reserve").textContent = `${numberFormatter.format(plan.reserves?.short_percent ?? 10)}%`;
  byId("weekly-reserve").textContent = `${numberFormatter.format(plan.reserves?.weekly_percent ?? 15)}%`;
  byId("weekly-slots").textContent = plan.weekly_slots_remaining ? `${plan.weekly_slots_remaining}个` : "--";
  byId("data-source").textContent = snapshot.source || "--";
  const warning = byId("warning-text");
  const messages = snapshot.warnings || [];
  warning.hidden = messages.length === 0;
  warning.textContent = messages.join("；");
}

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function interpolateValue(points, timestamp, field, resetField = null) {
  if (!points.length) return null;
  const edgeTolerance = 120;
  if (timestamp <= points[0].observed_at) {
    return points[0].observed_at - timestamp <= edgeTolerance ? Number(points[0][field]) : null;
  }
  const last = points[points.length - 1];
  if (timestamp >= last.observed_at) {
    const value = last[field];
    return timestamp - last.observed_at <= edgeTolerance && value != null ? Number(value) : null;
  }
  let low = 0;
  let high = points.length - 1;
  while (high - low > 1) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle].observed_at <= timestamp) low = middle;
    else high = middle;
  }
  const left = points[low];
  const right = points[high];
  if (left[field] == null || right[field] == null) return null;
  if (resetField && left[resetField] !== right[resetField]) {
    return timestamp - left.observed_at <= right.observed_at - timestamp
      ? Number(left[field])
      : Number(right[field]);
  }
  const span = Math.max(1, right.observed_at - left.observed_at);
  const progress = clamp((timestamp - left.observed_at) / span, 0, 1);
  return Number(left[field]) + (Number(right[field]) - Number(left[field])) * progress;
}

function formatChartTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function setChartTooltipRow(id, value, exactValue = "") {
  const row = byId(`chart-tooltip-${id}`);
  row.hidden = value == null;
  if (value == null) return;
  const output = byId(`chart-tooltip-${id}-value`);
  output.textContent = value;
  output.title = exactValue;
}

function updateChartTooltip(model, timestamp, x) {
  const shortUsed = interpolateValue(model.series[0].points, timestamp, "used_percent", "resets_at");
  const weeklyUsed = interpolateValue(model.series[1].points, timestamp, "used_percent", "resets_at");
  const dailyTokens = interpolateValue(model.tokenPoints, timestamp, "daily_tokens", "daily_resets_at");
  const weeklyTokens = interpolateValue(model.tokenPoints, timestamp, "weekly_tokens", "weekly_resets_at");

  byId("chart-tooltip-time").textContent = formatChartTime(timestamp);
  setChartTooltipRow(
    "short",
    shortUsed == null ? null : `${percentFormatter.format(shortUsed)}% 已用`,
  );
  setChartTooltipRow(
    "weekly",
    weeklyUsed == null ? null : `${percentFormatter.format(weeklyUsed)}% 已用`,
  );
  setChartTooltipRow(
    "daily",
    dailyTokens == null ? null : formatTokens(dailyTokens),
    dailyTokens == null ? "" : `${exactFormatter.format(Math.round(dailyTokens))} Token`,
  );
  setChartTooltipRow(
    "weekly-tokens",
    weeklyTokens == null ? null : formatTokens(weeklyTokens),
    weeklyTokens == null ? "" : `${exactFormatter.format(Math.round(weeklyTokens))} Token`,
  );

  const tooltip = byId("quota-chart-tooltip");
  tooltip.hidden = false;
  const tooltipWidth = tooltip.offsetWidth || 156;
  const preferredLeft = x + 8;
  const left = preferredLeft + tooltipWidth <= model.width - 3
    ? preferredLeft
    : x - tooltipWidth - 8;
  tooltip.style.transform = `translate3d(${Math.round(clamp(left, 3, model.width - tooltipWidth - 3))}px, 0, 0)`;
}

function drawChartOverlay(context, model) {
  if (!state.chartPointer.visible) {
    byId("quota-chart-tooltip").hidden = true;
    return;
  }
  const timestamp = model.start + model.rangeSeconds * state.chartPointer.ratio;
  const x = model.padding.left + model.plotWidth * state.chartPointer.ratio;
  context.save();
  context.beginPath();
  context.setLineDash([3, 3]);
  context.lineWidth = 1;
  context.strokeStyle = cssColor("--chart-crosshair", "#5f6368");
  context.moveTo(x, model.padding.top);
  context.lineTo(x, model.height - model.padding.bottom);
  context.stroke();
  context.setLineDash([]);
  for (const item of model.series) {
    const value = interpolateValue(item.points, timestamp, "used_percent", "resets_at");
    if (value == null) continue;
    const y = model.padding.top + model.plotHeight * (1 - clamp(value, 0, 100) / 100);
    context.beginPath();
    context.lineWidth = 2;
    context.fillStyle = cssColor("--surface", "#ffffff");
    context.strokeStyle = item.color;
    context.arc(x, y, 3.5, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }
  context.restore();
  updateChartTooltip(model, timestamp, x);
}

function formatChartRange(seconds) {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return remainingMinutes ? `${hours}小时${remainingMinutes}分` : `${hours} 小时`;
}

function resolveChartDomain(now, history, tokenHistory) {
  const maximumRange = state.chartHours * 3600;
  const cutoff = now - maximumRange;
  const timestamps = [...history, ...tokenHistory]
    .map((item) => Number(item.observed_at || 0))
    .filter((timestamp) => timestamp >= cutoff && timestamp <= now)
    .sort((left, right) => left - right)
    .filter((timestamp, index, values) => index === 0 || timestamp !== values[index - 1]);
  if (!timestamps.length) {
    return { start: cutoff, rangeSeconds: maximumRange, adaptive: false };
  }
  let continuousStart = timestamps[0];
  for (let index = timestamps.length - 1; index > 0; index -= 1) {
    if (timestamps[index] - timestamps[index - 1] > CHART_CONTINUITY_GAP_SECONDS) {
      continuousStart = timestamps[index];
      break;
    }
  }
  const observedDuration = Math.max(60, now - continuousStart);
  const rangeSeconds = Math.min(maximumRange, observedDuration);
  return {
    start: now - rangeSeconds,
    rangeSeconds,
    adaptive: rangeSeconds < maximumRange * 0.98,
  };
}

function drawChart() {
  const canvas = byId("quota-chart");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(140, rect.width);
  const height = Math.max(70, rect.height);
  canvas.width = Math.round(width * pixelRatio);
  canvas.height = Math.round(height * pixelRatio);
  const context = canvas.getContext("2d");
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, width, height);

  const padding = { top: 5, right: 3, bottom: 4, left: 3 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  context.lineWidth = 1;
  context.strokeStyle = cssColor("--chart-grid", "#e0e3e7");
  for (const value of [0, 50, 100]) {
    const y = padding.top + plotHeight * (1 - value / 100);
    context.beginPath();
    context.moveTo(padding.left, y);
    context.lineTo(width - padding.right, y);
    context.stroke();
  }

  const history = state.snapshot?.quota_history || [];
  const tokenHistory = state.snapshot?.token_history || [];
  const now = Date.now() / 1000;
  const domain = resolveChartDomain(now, history, tokenHistory);
  const { start, rangeSeconds } = domain;
  const rangeLabel = formatChartRange(rangeSeconds);
  byId("chart-range-label").textContent = domain.adaptive ? `连续 ${rangeLabel}` : `最近 ${rangeLabel}`;
  byId("chart-range-start").textContent = `${rangeLabel}前`;
  const series = [
    {
      points: history.filter((item) => item.observed_at >= start && item.window_minutes >= 240 && item.window_minutes <= 360),
      color: cssColor("--green", "#168a67"),
    },
    {
      points: history.filter((item) => item.observed_at >= start && item.window_minutes >= 9000),
      color: cssColor("--blue", "#0b57d0"),
    },
  ];
  for (const item of series) {
    if (!item.points.length) continue;
    context.beginPath();
    context.lineWidth = 2;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.strokeStyle = item.color;
    item.points.forEach((point, index) => {
      const x = padding.left + plotWidth * clamp((point.observed_at - start) / rangeSeconds, 0, 1);
      const y = padding.top + plotHeight * (1 - clamp(point.used_percent, 0, 100) / 100);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  }

  const model = {
    width,
    height,
    padding,
    plotWidth,
    plotHeight,
    start,
    rangeSeconds,
    series,
    tokenPoints: tokenHistory.filter((item) => item.observed_at >= start),
  };
  drawChartOverlay(context, model);
}

function scheduleChartDraw() {
  if (state.chartFrame) return;
  state.chartFrame = requestAnimationFrame(() => {
    state.chartFrame = 0;
    drawChart();
  });
}

function setChartPointerFromEvent(event) {
  const rect = byId("quota-chart").getBoundingClientRect();
  state.chartPointer.ratio = clamp((event.clientX - rect.left) / Math.max(1, rect.width), 0, 1);
  state.chartPointer.visible = true;
}

function handleChartPointerMove(event) {
  if (state.chartPointer.locked) return;
  setChartPointerFromEvent(event);
  scheduleChartDraw();
}

function handleChartPointerLeave() {
  if (state.chartPointer.locked) return;
  state.chartPointer.visible = false;
  scheduleChartDraw();
}

function handleChartClick(event) {
  if (state.chartPointer.locked) {
    state.chartPointer.locked = false;
    state.chartPointer.visible = false;
  } else {
    setChartPointerFromEvent(event);
    state.chartPointer.locked = true;
  }
  scheduleChartDraw();
}

function handleChartKeydown(event) {
  if (["ArrowLeft", "ArrowRight"].includes(event.key)) {
    event.preventDefault();
    state.chartPointer.visible = true;
    state.chartPointer.ratio = clamp(
      state.chartPointer.ratio + (event.key === "ArrowLeft" ? -0.02 : 0.02),
      0,
      1,
    );
    scheduleChartDraw();
  } else if (["Enter", " "].includes(event.key)) {
    event.preventDefault();
    state.chartPointer.visible = !state.chartPointer.locked;
    state.chartPointer.locked = !state.chartPointer.locked;
    scheduleChartDraw();
  } else if (event.key === "Escape") {
    state.chartPointer.locked = false;
    state.chartPointer.visible = false;
    scheduleChartDraw();
  }
}

function render() {
  updateUsageStreak();
  updateQuotaCard("weekly", "weekly");
  renderSummary();
  renderTasks();
  if (byId("task-detail-dialog").open) renderTaskDetail();
  if (byId("all-tasks-dialog").open && !document.activeElement?.closest("#all-tasks-dialog")) renderAllTasks();
  drawChart();
  const online = state.snapshot?.health === "ok";
  const quotaWindows = state.snapshot?.quota_windows || [];
  const quotaStale = quotaWindows.some((item) => item.is_stale);
  byId("live-dot").className = `live-dot ${online ? (quotaStale ? "warning" : "online") : "error"}`;
  byId("connection-label").textContent = !online
    ? "数据源异常"
    : quotaStale
      ? "Token 实时 · 额度待上报"
      : quotaWindows.length
        ? "实时采集中"
        : "Token 实时 · 额度未报告";
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
document.querySelectorAll("[data-theme-value]").forEach((button) => {
  button.addEventListener("click", () => applyTheme(button.dataset.themeValue));
});
const quotaChart = byId("quota-chart");
quotaChart.addEventListener("pointerenter", handleChartPointerMove);
quotaChart.addEventListener("pointermove", handleChartPointerMove);
quotaChart.addEventListener("pointerleave", handleChartPointerLeave);
quotaChart.addEventListener("click", handleChartClick);
quotaChart.addEventListener("keydown", handleChartKeydown);
for (const dialog of document.querySelectorAll("dialog")) {
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

setInterval(() => {
  byId("footer-clock").textContent = new Date().toLocaleString("zh-CN", { hour12: false });
  if (state.snapshot) {
    updateUsageStreak();
    updateQuotaCard("weekly", "weekly");
  }
}, 1000);

applyTheme(storedTheme(), false);
fetchStatus();
setInterval(fetchStatus, 1000);
