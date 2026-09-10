// @bundle-order: 1
// ---------------------------------------------------------------------------
// pricing —— 价格表与峰谷判定（纯数据 + 纯函数）
//
// 设计约束（为可移植性刻意如此）：
//   * 本文件不 import 任何东西、不接触 DSH / Node / 浏览器 API；
//   * 因此它能被三种运行形态同时复用：
//       1) 常驻插件（ESM `import`）
//       2) 动态 Cordis 插件（由 tools/build.mjs 内联进函数体）
//       3) 独立 Node 脚本 / 单元测试
//   * 所有导出一律是纯函数：同样的输入必得同样的输出，便于单测与优化。
//
// 价格来源：https://api-docs.deepseek.com/quick_start/pricing
// 单位：USD / 每 100 万 tokens；数组顺序为 [offPeak, peak]。
// 峰时：UTC 周一至周五 01:00-04:00 与 06:00-10:00，其余为谷时（谷时价 = 峰时价的一半）。
// ---------------------------------------------------------------------------

export const PRICING_DEFAULT = {
  version: '2026-09-14',
  source: 'https://api-docs.deepseek.com/quick_start/pricing',
  currency: 'USD',
  unit: 'per_1m_tokens',
  // 峰时段（UTC）。days 用 0=周日 … 6=周六，与 Date#getUTCDay 一致。
  peak: { utcDays: [1, 2, 3, 4, 5], utcHours: [[1, 4], [6, 10]] },
  models: {
    'deepseek-flash': { cacheHit: [0.003, 0.006], cacheMiss: [0.15, 0.3], output: [0.6, 1.2] },
    'deepseek-v4-pro': { cacheHit: [0.022, 0.044], cacheMiss: [0.66, 1.32], output: [1.98, 3.96] },
  },
  // 官方历史/别名 id → 计费模型。找不到时用 fallbackModel，并在结果里标 priced:false。
  aliases: {
    'deepseek-v4-flash': 'deepseek-flash',
    'deepseek-v4-flash-vision-exp': 'deepseek-flash',
    'deepseek-v4.1-flash': 'deepseek-flash',
    'deepseek-v4-pro-0813': 'deepseek-v4-pro',
    'deepseek-chat': 'deepseek-flash',
    'deepseek-reasoner': 'deepseek-v4-pro',
  },
  fallbackModel: 'deepseek-flash',
}

/** 合并外部覆盖（config/pricing.json）到默认表；深合并 models，浅合并其余。 */
export function mergePricing(overrides) {
  const base = PRICING_DEFAULT
  if (!overrides || typeof overrides !== 'object') return base
  return {
    ...base,
    ...overrides,
    peak: { ...base.peak, ...(overrides.peak || {}) },
    models: { ...base.models, ...(overrides.models || {}) },
    aliases: { ...base.aliases, ...(overrides.aliases || {}) },
  }
}

/** 把任意模型 id 归一到价格表里的键。 */
export function resolvePriceModel(table, model) {
  const id = String(model || '')
  if (table.models[id]) return id
  const alias = table.aliases[id]
  if (alias && table.models[alias]) return alias
  return table.fallbackModel
}

/** 该时刻是否处于峰时（按 UTC 判定，与官方口径一致）。 */
export function isPeakAt(table, date) {
  const d = date instanceof Date ? date : new Date(date)
  const days = table.peak.utcDays || []
  if (!days.includes(d.getUTCDay())) return false
  const minutes = d.getUTCHours() * 60 + d.getUTCMinutes()
  for (const [from, to] of table.peak.utcHours || []) {
    if (minutes >= from * 60 && minutes < to * 60) return true
  }
  return false
}

/** 取某模型在给定时刻的三档单价（USD / 1M tokens）。 */
export function priceOf(table, model, at) {
  const key = resolvePriceModel(table, model)
  const row = table.models[key]
  const idx = isPeakAt(table, at) ? 1 : 0
  return {
    model: key,
    peak: idx === 1,
    cacheHit: row.cacheHit[idx],
    cacheMiss: row.cacheMiss[idx],
    output: row.output[idx],
    known: String(model || '') === key || (table.aliases || {})[String(model || '')] === key,
  }
}

/**
 * 用一次调用的 token 用量算钱。
 * 注意 harness 的 TokenUsage 是「互斥计数」：inputTokens 已经是未命中部分，
 * cacheReadTokens 才是命中部分（见 dsh-llm-deepseek 的 mapUsage）。
 *
 * @returns 各分项与合计（USD），以及 used/estimated 明细供 UI 归类展示。
 */
export function costOfUsage(table, model, usage, at) {
  const p = priceOf(table, model, at)
  const cacheMissTokens = num(usage && usage.inputTokens)
  const cacheHitTokens = num(usage && usage.cacheReadTokens)
  const outputTokens = num(usage && usage.outputTokens)
  const perM = 1e6
  const cacheMissCost = (cacheMissTokens / perM) * p.cacheMiss
  const cacheHitCost = (cacheHitTokens / perM) * p.cacheHit
  const outputCost = (outputTokens / perM) * p.output
  return {
    model: p.model,
    peak: p.peak,
    known: p.known,
    cacheMissTokens,
    cacheHitTokens,
    outputTokens,
    reasoningTokens: num(usage && usage.reasoningTokens),
    cacheWriteTokens: num(usage && usage.cacheWriteTokens),
    cacheMissCost,
    cacheHitCost,
    outputCost,
    total: cacheMissCost + cacheHitCost + outputCost,
  }
}

function num(value) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0
}
