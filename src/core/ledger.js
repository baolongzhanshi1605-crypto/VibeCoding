// @bundle-order: 2
// ---------------------------------------------------------------------------
// ledger —— 用量账本与聚合（纯数据 + 纯函数）
//
// 记账口径（回答「钱花在哪里」）：
//   * 维度：模型 / 会话 / 日期 / 峰谷 / 用途（对话、压缩、标题、子代理…）
//   * 分项：缓存命中输入、缓存未命中输入、输出、图片视觉 token（估算，不计费）
//   * 明细环形缓冲：只留最近 N 条调用，防止长时间运行内存无界增长；
//     聚合计数器是精确累加，不受环形缓冲淘汰影响。
//
// 本文件同样零依赖，可被常驻插件、动态插件内联、Node 脚本复用。
// 依赖：pricing.js（需先于本文件内联，见 @bundle-order）。
// ---------------------------------------------------------------------------

/** 明细环形缓冲上限。 */
export const MAX_CALL_ROWS = 1000

/** 新建一个空账本。 */
export function createLedger() {
  return {
    createdAt: Date.now(),
    /** 这是第几次运行（从持久化数据恢复时递增）。 */
    runs: 1,
    /** 是否成功从磁盘恢复过累计数据（UI 用它区分「累计」与「本次」）。 */
    restored: false,
    /** 上次从历史会话日志回填的时刻；存在即表示不必再自动回填。 */
    backfilledAt: 0,
    calls: 0,
    rows: [],
    dropped: 0,
    // 分项 token / 成本
    cacheHitTokens: 0,
    cacheMissTokens: 0,
    outputTokens: 0,
    reasoningTokens: 0,
    imageTokensEstimate: 0,
    costTotal: 0,
    costCacheHit: 0,
    costCacheMiss: 0,
    costOutput: 0,
    costPeak: 0,
    costOffPeak: 0,
    unpricedCalls: 0,
    failedCalls: 0,
    byModel: {},
    byDay: {},
    byPurpose: {},
    bySession: {},
  }
}

function bucket(map, key) {
  if (!map[key]) {
    map[key] = {
      calls: 0,
      cacheHitTokens: 0,
      cacheMissTokens: 0,
      outputTokens: 0,
      imageTokensEstimate: 0,
      cost: 0,
      costCacheHit: 0,
      costCacheMiss: 0,
      costOutput: 0,
      peakCost: 0,
      offPeakCost: 0,
      firstAt: 0,
      lastAt: 0,
    }
  }
  return map[key]
}

function bump(target, cost, atMs) {
  target.calls += 1
  target.cacheHitTokens += cost.cacheHitTokens
  target.cacheMissTokens += cost.cacheMissTokens
  target.outputTokens += cost.outputTokens
  target.cost += cost.total
  target.costCacheHit += cost.cacheHitCost
  target.costCacheMiss += cost.cacheMissCost
  target.costOutput += cost.outputCost
  if (cost.peak) target.peakCost += cost.total
  else target.offPeakCost += cost.total
  if (!target.firstAt || atMs < target.firstAt) target.firstAt = atMs
  if (atMs > target.lastAt) target.lastAt = atMs
}

/**
 * 记一次模型调用。
 * @param ledger createLedger() 的产物（原地修改）
 * @param info { at, model, provider, purpose, sessionId, usage, cost, imageTokensEstimate, ok }
 */
export function recordCall(ledger, info) {
  const at = info.at instanceof Date ? info.at : new Date(info.at || Date.now())
  const cost = info.cost || {
    cacheHitTokens: 0, cacheMissTokens: 0, outputTokens: 0,
    cacheHitCost: 0, cacheMissCost: 0, outputCost: 0, total: 0, peak: false, known: false, model: 'unknown',
  }
  const ok = info.ok !== false

  ledger.calls += 1
  if (!ok) ledger.failedCalls += 1
  if (!cost.known) ledger.unpricedCalls += 1

  ledger.cacheHitTokens += cost.cacheHitTokens
  ledger.cacheMissTokens += cost.cacheMissTokens
  ledger.outputTokens += cost.outputTokens
  ledger.reasoningTokens += cost.reasoningTokens || 0
  ledger.imageTokensEstimate += info.imageTokensEstimate || 0
  ledger.costTotal += cost.total
  ledger.costCacheHit += cost.cacheHitCost
  ledger.costCacheMiss += cost.cacheMissCost
  ledger.costOutput += cost.outputCost
  if (cost.peak) ledger.costPeak += cost.total
  else ledger.costOffPeak += cost.total

  const atMs = at.getTime()
  bump(bucket(ledger.byModel, cost.model), cost, atMs)
  bump(bucket(ledger.byDay, dayKey(at)), cost, atMs)
  bump(bucket(ledger.byPurpose, info.purpose || 'chat'), cost, atMs)
  // 按会话归因：Client 侧用当前 sessionId 过滤，就能回答「这个对话花了多少」。
  if (info.sessionId) bump(bucket(ledger.bySession, String(info.sessionId)), cost, atMs)

  const row = {
    at: at.toISOString(),
    model: cost.model,
    provider: String(info.provider || ''),
    purpose: info.purpose || 'chat',
    sessionId: String(info.sessionId || ''),
    cacheHitTokens: cost.cacheHitTokens,
    cacheMissTokens: cost.cacheMissTokens,
    outputTokens: cost.outputTokens,
    cost: cost.total,
    peak: !!cost.peak,
    ok,
  }
  ledger.rows.push(row)
  if (ledger.rows.length > MAX_CALL_ROWS) {
    ledger.rows.splice(0, ledger.rows.length - MAX_CALL_ROWS)
    ledger.dropped += 1
  }
  return row
}

/** UTC 日期键 YYYY-MM-DD。 */
export function dayKey(date) {
  const d = date instanceof Date ? date : new Date(date)
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** 缓存命中率（命中 tokens / 全部输入 tokens），0..1。 */
export function cacheHitRate(agg) {
  const total = (agg.cacheHitTokens || 0) + (agg.cacheMissTokens || 0)
  return total > 0 ? (agg.cacheHitTokens || 0) / total : 0
}

/** 把账本压成可 JSON 化的只读快照（给 UI 用），并算出派生指标。 */
export function summarize(ledger, options = {}) {
  const topN = options.topN || 8
  const models = rank(ledger.byModel, topN)
  const days = Object.keys(ledger.byDay).sort().slice(-14).map((k) => ({
    day: k, ...ledger.byDay[k],
  }))
  return {
    since: new Date(ledger.createdAt).toISOString(),
    runs: ledger.runs || 1,
    restored: ledger.restored === true,
    calls: ledger.calls,
    failedCalls: ledger.failedCalls,
    unpricedCalls: ledger.unpricedCalls,
    cacheHitTokens: ledger.cacheHitTokens,
    cacheMissTokens: ledger.cacheMissTokens,
    outputTokens: ledger.outputTokens,
    reasoningTokens: ledger.reasoningTokens,
    imageTokensEstimate: ledger.imageTokensEstimate,
    cacheHitRate: cacheHitRate(ledger),
    costTotal: ledger.costTotal,
    costCacheHit: ledger.costCacheHit,
    costCacheMiss: ledger.costCacheMiss,
    costOutput: ledger.costOutput,
    costPeak: ledger.costPeak,
    costOffPeak: ledger.costOffPeak,
    models,
    purposes: rank(ledger.byPurpose, topN),
    sessions: rank(ledger.bySession, topN),
    days,
    recent: ledger.rows.slice(-topN).reverse(),
  }
}

function rank(map, topN) {
  return Object.keys(map)
    .map((key) => ({ key, ...map[key] }))
    .sort((a, b) => b.cost - a.cost)
    .slice(0, topN)
}

// --- 持久化：把「累计」活过重启 ---------------------------------------------

/** 账本文件格式版本。改结构时递增，旧文件会被安全忽略而不是读出垃圾。 */
export const LEDGER_FORMAT_VERSION = 1

/** 持久化时每个聚合维度最多保留多少条（防止 bySession 无限增长）。 */
export const MAX_PERSISTED_BUCKETS = 60

/** 按 cost 降序截断一个聚合 map。 */
function pruneBuckets(map, limit) {
  const keys = Object.keys(map)
  if (keys.length <= limit) return map
  return Object.fromEntries(
    keys.sort((a, b) => (map[b].cost || 0) - (map[a].cost || 0)).slice(0, limit).map((key) => [key, map[key]]),
  )
}

/**
 * 导出可持久化的聚合快照。
 * 刻意**不导出** `rows`（明细环形缓冲）：它只对「最近调用」表有意义，
 * 而且是唯一会无界增长的部分；累计数字全部来自聚合计数器。
 */
export function exportLedger(ledger) {
  return {
    version: LEDGER_FORMAT_VERSION,
    createdAt: ledger.createdAt,
    updatedAt: Date.now(),
    runs: ledger.runs || 1,
    backfilledAt: ledger.backfilledAt || 0,
    calls: ledger.calls,
    failedCalls: ledger.failedCalls,
    unpricedCalls: ledger.unpricedCalls,
    cacheHitTokens: ledger.cacheHitTokens,
    cacheMissTokens: ledger.cacheMissTokens,
    outputTokens: ledger.outputTokens,
    reasoningTokens: ledger.reasoningTokens,
    imageTokensEstimate: ledger.imageTokensEstimate,
    costTotal: ledger.costTotal,
    costCacheHit: ledger.costCacheHit,
    costCacheMiss: ledger.costCacheMiss,
    costOutput: ledger.costOutput,
    costPeak: ledger.costPeak,
    costOffPeak: ledger.costOffPeak,
    byModel: pruneBuckets(ledger.byModel, MAX_PERSISTED_BUCKETS),
    byDay: pruneBuckets(ledger.byDay, MAX_PERSISTED_BUCKETS),
    byPurpose: pruneBuckets(ledger.byPurpose, MAX_PERSISTED_BUCKETS),
    bySession: pruneBuckets(ledger.bySession, MAX_PERSISTED_BUCKETS),
  }
}

/**
 * 把持久化数据装回账本（原地修改）。
 * 任何字段缺失、类型不对、版本不认识 —— 一律忽略该字段并保持 0，**绝不抛**：
 * 一个坏掉的账本文件不该让插件失效。
 * @returns 是否成功装载（用于 UI 显示「已恢复」还是「全新开始」）
 */
export function importLedger(ledger, data) {
  if (!data || typeof data !== 'object') return false
  if (data.version !== LEDGER_FORMAT_VERSION) return false

  const count = (value) => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0)
  const buckets = (value) => (value && typeof value === 'object' && !Array.isArray(value) ? value : {})

  ledger.createdAt = count(data.createdAt) || ledger.createdAt
  ledger.runs = count(data.runs) || 1
  ledger.backfilledAt = count(data.backfilledAt)
  ledger.calls = count(data.calls)
  ledger.failedCalls = count(data.failedCalls)
  ledger.unpricedCalls = count(data.unpricedCalls)
  ledger.cacheHitTokens = count(data.cacheHitTokens)
  ledger.cacheMissTokens = count(data.cacheMissTokens)
  ledger.outputTokens = count(data.outputTokens)
  ledger.reasoningTokens = count(data.reasoningTokens)
  ledger.imageTokensEstimate = count(data.imageTokensEstimate)
  ledger.costTotal = count(data.costTotal)
  ledger.costCacheHit = count(data.costCacheHit)
  ledger.costCacheMiss = count(data.costCacheMiss)
  ledger.costOutput = count(data.costOutput)
  ledger.costPeak = count(data.costPeak)
  ledger.costOffPeak = count(data.costOffPeak)
  ledger.byModel = buckets(data.byModel)
  ledger.byDay = buckets(data.byDay)
  ledger.byPurpose = buckets(data.byPurpose)
  ledger.bySession = buckets(data.bySession)
  // 只有真的恢复出「有内容」的累计才算恢复成功。
  // 空文件（全 0）也返回 true 的话，界面会显示「已从磁盘恢复累计」而数字是 0 ——
  // 那和「功能没生效」长得一模一样，正是最容易被误判成 bug 的情形。
  ledger.restored = ledger.calls > 0
  return true
}
