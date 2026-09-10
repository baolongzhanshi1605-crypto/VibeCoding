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
