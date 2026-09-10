// @bundle-order: 4
// ---------------------------------------------------------------------------
// format —— 展示层纯函数（零依赖，Host 与 Client 共用）
//
// 放在 core 里而不是 Client 里的理由：常驻插件的 Host 侧也会在
// 工具返回值 / 日志摘要中复用同一套数字口径，避免两处格式漂移。
// ---------------------------------------------------------------------------

const CURRENCY_SYMBOL = { CNY: '¥', USD: '$', EUR: '€' }

/**
 * 花费的展示币种与汇率。
 *
 * 为什么需要它：官方价格表以**美元**发布（USD / 百万 tokens），而账单与余额是人民币，
 * 所以账本内部一律以美元记账（权威口径、不与汇率耦合），只在**展示时**折算。
 * 想改币种或汇率，只改这里，然后 node tools/build.mjs。
 * 余额不走这套折算——它按接口返回的币种原样显示。
 */
export const DEFAULT_MONEY = {
  currency: 'CNY',
  rate: 7.1,
  sourceCurrency: 'USD',
  note: '官方价格表以美元发布，此处按固定汇率折算为人民币；改 src/core/format.js 的 DEFAULT_MONEY 可调整。',
}

/** 把「美元记账值」折算成展示币种。money 缺省时退回 DEFAULT_MONEY。 */
export function fmtCost(valueUsd, money) {
  const m = money && typeof money === 'object' ? money : DEFAULT_MONEY
  const currency = m.currency || DEFAULT_MONEY.currency
  const rate = Number(m.rate) > 0 ? Number(m.rate) : 1
  return fmtMoney((Number(valueUsd) || 0) * rate, currency)
}

/** 金额：小额保留 4 位有效小数，大额保留 2 位。 */
export function fmtMoney(value, currency = 'USD') {
  const n = Number(value) || 0
  const symbol = CURRENCY_SYMBOL[currency] || ''
  const abs = Math.abs(n)
  let text
  if (abs === 0) text = '0.00'
  else if (abs < 0.01) text = n.toFixed(4)
  else if (abs < 1) text = n.toFixed(3)
  else text = n.toFixed(2)
  return symbol ? `${symbol}${text}` : `${text} ${currency}`
}

/** 大整数可读化：1234567 → 1.23M。 */
export function fmtTokens(value) {
  const n = Number(value) || 0
  const abs = Math.abs(n)
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return String(Math.round(n))
}

/** 百分比。 */
export function fmtPct(value, digits = 1) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

/** 相对时间：刚刚 / 3 分钟前 / 2 小时前。 */
export function fmtAgo(ms, now = Date.now()) {
  if (!Number.isFinite(ms) || ms <= 0) return '未刷新'
  const delta = Math.max(0, now - ms)
  const s = Math.floor(delta / 1000)
  if (s < 5) return '刚刚'
  if (s < 60) return `${s} 秒前`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}

/** 余额紧凑串：¥110.00。 */
export function fmtBalance(balance) {
  if (!balance || !balance.ok) return '—'
  const first = (balance.infos || [])[0]
  if (!first) return '—'
  return fmtMoney(first.totalBalance, first.currency)
}
