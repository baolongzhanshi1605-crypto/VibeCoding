// ===========================================================================
// dsh-api-balance · Client 半（apply 函数体）
//
// 与 host.body.js 一样，本文件被 tools/build.mjs 内联成两种形态共用的函数体：
//   * 动态平面：cordis_define 的 code.client（浏览器内临时插件）
//   * 常驻平面：package/lib/client.js 的手写 __ModuleLoader__ 工厂
//
// 只能用：React.createElement（无 JSX）、ctx.get() 的服务、平台 builtin。
// UI 落点（三个都是 additive 的 list 槽，replaceRisk = none，不会遮挡原生界面）：
//   1. conversation.session.header.utilities —— 会话标题右侧的常驻小胶囊（点击展开明细）；
//   2. conversation.composer.dock            —— 输入框下方的「本对话消费」明细面板；
//   3. settings.section                      —— 设置里的完整仪表盘页。
// ===========================================================================

const ROUTE_PREFIX = '/dsh-api-balance'
const POLL_MS = 15000

/** 极简 createElement 包装，替代 JSX。 */
function h(type, props, ...children) {
  return React.createElement(type, props, ...children)
}

/** Host RPC：动态平面走 host.call，常驻平面走同源 HTTP 路由。 */
async function callHost(method, args) {
  if (typeof host !== 'undefined' && host && typeof host.call === 'function') {
    return host.call(method, args === undefined ? {} : args)
  }
  if (typeof fetch !== 'function') throw new Error('当前运行形态不支持 host.call，也没有 fetch')
  const response = await fetch(`${ROUTE_PREFIX}/${method}`, { method: 'GET', cache: 'no-store' })
  if (!response.ok) throw new Error(`Host 接口 ${method} 返回 HTTP ${response.status}`)
  return response.json()
}

/** 注入样式：动态平面用 styles builtin，常驻平面用样式服务。 */
function insertStyles(ctx, css) {
  if (typeof styles !== 'undefined' && styles && typeof styles.insert === 'function') {
    return styles.insert(css)
  }
  const service = ctx.get('styles')
  if (service && typeof service.insert === 'function') return service.insert(css)
  return () => {}
}

const CSS = `
.dab-pill{position:relative;display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;
  border:1px solid var(--dsw-alias-border-l1);border-radius:999px;background:transparent;
  color:var(--dsw-alias-label-secondary);font-size:12px;line-height:1;cursor:pointer;
  font-variant-numeric:tabular-nums;white-space:nowrap;
  pointer-events:auto;-webkit-app-region:no-drag;user-select:none;-webkit-user-select:none}
.dab-pill *{pointer-events:auto;cursor:pointer;-webkit-app-region:no-drag;user-select:none;-webkit-user-select:none}
.dab-hit{position:absolute;top:0;right:0;bottom:0;left:0;border-radius:999px;display:block}
.dab-pill:hover{background:var(--dsw-alias-interactive-bg-hover)}
.dab-pill.on{background:var(--dsw-alias-interactive-bg-active);border-color:var(--dsw-alias-border-l2)}
.dab-pill .caret{font-size:9px;color:var(--dsw-alias-label-tertiary);margin-left:1px}
.dab-dot{width:6px;height:6px;border-radius:50%;flex:0 0 auto}
.dab-dot.ok{background:var(--dsw-alias-state-success-primary)}
.dab-dot.warn{background:var(--dsw-alias-state-warn-primary)}
.dab-dot.err{background:var(--dsw-alias-state-error-primary)}
.dab-page{padding:4px 2px 32px;color:var(--dsw-alias-label-primary);font-size:13px}
.dab-h{font-size:15px;font-weight:600;margin:0 0 4px}
.dab-sub{color:var(--dsw-alias-label-tertiary);font-size:12px;margin:0 0 16px}
.dab-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.dab-card{border:1px solid var(--dsw-alias-border-l1);border-radius:10px;background:var(--dsw-alias-bg-layer-1);padding:11px 13px}
.dab-card .k{color:var(--dsw-alias-label-tertiary);font-size:11px;margin-bottom:6px}
.dab-card .v{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.2px}
.dab-card .n{color:var(--dsw-alias-label-tertiary);font-size:11px;margin-top:4px}
.dab-sec{margin:0 0 18px}
.dab-sec>h4{margin:0 0 8px;font-size:12px;font-weight:600;color:var(--dsw-alias-label-secondary)}
.dab-bar{display:grid;grid-template-columns:132px 1fr 92px;align-items:center;gap:10px;padding:4px 0;font-size:12px}
.dab-bar .t{color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dab-bar .m{height:7px;border-radius:999px;background:var(--dsw-alias-bg-layer-2);overflow:hidden}
.dab-bar .m>i{display:block;height:100%;border-radius:999px}
.dab-bar .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-primary)}
.dab-table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
.dab-table th{text-align:right;font-weight:500;color:var(--dsw-alias-label-tertiary);
  padding:5px 8px;border-bottom:1px solid var(--dsw-alias-border-l1);white-space:nowrap}
.dab-table th:first-child,.dab-table td:first-child{text-align:left}
.dab-table td{text-align:right;padding:5px 8px;border-bottom:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary)}
.dab-table td:first-child{color:var(--dsw-alias-label-primary)}
.dab-table tr:last-child td{border-bottom:none}
.dab-note{margin-top:10px;color:var(--dsw-alias-label-tertiary);font-size:11px;line-height:1.6}
.dab-err{margin:0 0 14px;padding:9px 11px;border-radius:8px;font-size:12px;
  border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-state-error-primary);
  background:var(--dsw-alias-bg-layer-1);word-break:break-all}
.dab-row{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.dab-btn{height:28px;padding:0 12px;border-radius:7px;font-size:12px;cursor:pointer;
  border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);
  color:var(--dsw-alias-label-primary)}
.dab-btn:hover{background:var(--dsw-alias-interactive-bg-hover)}
.dab-btn:disabled{opacity:.5;cursor:default}
.dab-sel{height:28px;border-radius:7px;font-size:12px;padding:0 6px;
  border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);
  color:var(--dsw-alias-label-primary)}
.dab-dock{margin:6px 0 0;border:1px solid var(--dsw-alias-border-l1);border-radius:10px;
  background:var(--dsw-alias-bg-layer-1);padding:12px 14px;font-size:12px;
  color:var(--dsw-alias-label-primary);font-variant-numeric:tabular-nums}
.dab-dock-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.dab-dock-head b{font-size:13px;font-weight:600}
.dab-dock-head .sp{flex:1}
.dab-mini{display:grid;grid-template-columns:repeat(auto-fit,minmax(92px,1fr));gap:8px;margin-bottom:10px}
.dab-mini>div{border:1px solid var(--dsw-alias-border-l1);border-radius:8px;padding:7px 9px}
.dab-mini .k{color:var(--dsw-alias-label-tertiary);font-size:10px;margin-bottom:3px}
.dab-mini .v{font-size:14px;font-weight:600}
.dab-x{border:none;background:transparent;color:var(--dsw-alias-label-tertiary);
  cursor:pointer;font-size:15px;line-height:1;padding:2px 6px;border-radius:5px}
.dab-x:hover{background:var(--dsw-alias-interactive-bg-hover);color:var(--dsw-alias-label-primary)}
`

// --- 展示层小工具（纯函数，Host/Client 同口径） -----------------------------

function pct(part, whole) {
  if (!whole) return 0
  return Math.max(0, Math.min(1, part / whole))
}

/** 缓存命中率：命中 tokens / 全部输入 tokens。与 Host 侧 cacheHitRate() 同口径。 */
function hitRateOf(agg) {
  const total = (agg.cacheHitTokens || 0) + (agg.cacheMissTokens || 0)
  return total > 0 ? (agg.cacheHitTokens || 0) / total : 0
}

/** 本地时钟 HH:MM:SS。 */
function fmtClock(value) {
  if (!value) return '—'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

// --- 展开面板的开关状态 -----------------------------------------------------
// 胶囊在会话标题栏、面板在输入框下方，是两个互不相邻的 Slot。
// 用一个 apply() 作用域内的小订阅表把它们连起来；插件停止时随之消失，不残留全局状态。

const panelStore = { open: false, listeners: new Set() }

function setPanelOpen(next) {
  panelStore.open = next
  for (const listener of Array.from(panelStore.listeners)) listener(next)
}

function usePanelOpen() {
  const [open, setOpen] = React.useState(panelStore.open)
  React.useEffect(() => {
    panelStore.listeners.add(setOpen)
    return () => { panelStore.listeners.delete(setOpen) }
  }, [])
  return [open, setPanelOpen]
}

function Card(key, value, note) {
  return h('div', { className: 'dab-card', key },
    h('div', { className: 'k' }, key),
    h('div', { className: 'v' }, value),
    note ? h('div', { className: 'n' }, note) : null,
  )
}

/**
 * 一条横向条形。
 * @param format 数值格式化函数——费用条传 fmtCost，token 条传 fmtTokens。
 *               早先版本写死 fmtMoney，导致「图片视觉 token」那一条把 token 数当钱显示。
 */
function Bar(label, value, max, color, format) {
  const render = typeof format === 'function' ? format : ((v) => String(v))
  return h('div', { className: 'dab-bar', key: label },
    h('div', { className: 't', title: label }, label),
    h('div', { className: 'm' }, h('i', { style: { width: `${pct(value, max) * 100}%`, background: color } })),
    h('div', { className: 'v' }, render(value)),
  )
}

// --- 数据获取 hook ----------------------------------------------------------

/**
 * 拉取一份 Host 快照并定时轮询。
 * @param enabled 传 false 时完全不请求、不轮询——折叠状态的面板不该产生任何流量。
 *                hook 仍然无条件调用（React 规则），只在 effect 内部按需跳过。
 */
function useSnapshot(ctx, timer, enabled) {
  const on = enabled === undefined ? true : enabled
  const [snap, setSnap] = React.useState({ loading: true, data: null, error: null, refreshing: false })
  const load = async (isManual) => {
    if (isManual) setSnap((prev) => ({ ...prev, refreshing: true }))
    try {
      const data = await callHost(isManual ? 'refresh' : 'snapshot')
      setSnap({ loading: false, data, error: null, refreshing: false })
    } catch (error) {
      setSnap((prev) => ({ ...prev, loading: false, refreshing: false, error: String((error && error.message) || error) }))
    }
  }
  React.useEffect(() => {
    if (!on) return undefined
    let alive = true
    const tick = async (manual) => { if (alive) await load(manual) }
    void tick(false)
    let dispose = () => {}
    if (timer && typeof timer.interval === 'function') {
      dispose = timer.interval(() => { void tick(false) }, POLL_MS)
    }
    return () => { alive = false; dispose() }
  }, [on])
  return [snap, load]
}

// --- 会话标题右侧的小胶囊 ---------------------------------------------------

/**
 * 会话标题右侧的小胶囊。
 *
 * 结构上刻意拆成「调用 hook」+「纯渲染」两段：hook 必须无条件调用（React 规则），
 * 渲染整体包在 try/catch 里——任何数据异常都降级成一个小徽章，
 * 不会把会话标题那一行渲染崩。对应 docs/ROLLBACK.md 威胁模型里的 T3（Client 渲染异常）。
 */
function BalancePill(props) {
  const [snap] = useSnapshot(props.ctx, props.timer, true)
  const [open, toggle] = usePanelOpen()
  try {
    return pillBody(snap, open, toggle)
  } catch (error) {
    return h('span', {
      className: 'dab-pill',
      title: `余额面板渲染失败（已安全降级）：${String((error && error.message) || error)}`,
    }, '余额 —')
  }
}

function pillBody(snap, open, toggle) {
  const data = snap.data
  const balance = data && data.balance
  const usage = (data && data.usage) || null
  const status = !data ? 'warn' : (balance && balance.ok ? 'ok' : 'err')
  const title = [
    balance && balance.ok ? `余额：${fmtBalance(balance)}` : `余额读取失败：${(balance && balance.error) || snap.error || '等待中'}`,
    usage ? `本次进程累计花费 ≈ ${fmtCost(usage.costTotal, money)}（${usage.calls} 次调用）` : '',
    usage ? `缓存命中率 ${fmtPct(usage.cacheHitRate)}` : '',
    data ? `刷新于 ${fmtAgo(balance && balance.at, data.now)}` : '',
  ].filter(Boolean).join('\n')

  return h('button', {
    className: `dab-pill${open ? ' on' : ''}`,
    type: 'button',
    title: `${title}\n\n点击展开/收起本对话的消费明细`,
    onClick: () => toggle(!open),
  },
  h('span', { className: 'dab-hit', key: 'hit' }),
  h('span', { className: `dab-dot ${status}`, key: 'dot' }),
  h('span', { key: 'amount' }, balance && balance.ok ? fmtBalance(balance) : '余额 —'),
  usage && usage.calls > 0
    ? h('span', { key: 'cost', style: { color: 'var(--dsw-alias-label-tertiary)' } }, `· ${fmtCost(usage.costTotal, money)}`)
    : null,
  h('span', { className: 'caret', key: 'caret' }, open ? '▴' : '▾'),
  )
}

// --- 设置页：完整仪表盘 -----------------------------------------------------

/** 设置页仪表盘：与胶囊同构——hook 与渲染分离，渲染全程受 try/catch 保护。 */
function Dashboard(props) {
  const [snap, load] = useSnapshot(props.ctx, props.timer)
  try {
    return dashboardBody(snap, load)
  } catch (error) {
    return h('div', { className: 'dab-page' },
      h('div', { className: 'dab-err' },
        `面板渲染失败（已安全降级，不影响 DSH 其余部分）：${String((error && error.message) || error)}`),
      h('button', { className: 'dab-btn', onClick: () => { void load(true) } }, '重试'),
    )
  }
}

function dashboardBody(snap, load) {
  const data = snap.data

  if (snap.loading && !data) {
    return h('div', { className: 'dab-page' }, h('div', { className: 'dab-sub' }, '正在读取 DeepSeek API 余额与用量…'))
  }
  if (!data) {
    return h('div', { className: 'dab-page' },
      h('div', { className: 'dab-err' }, `读取失败：${snap.error || '未知错误'}`),
      h('button', { className: 'dab-btn', onClick: () => { void load(true) } }, '重试'),
    )
  }

  const balance = data.balance || {}
  const usage = data.usage || {}
  const pricing = data.pricing || {}
  const apiKey = data.apiKey || {}
  const money = data.money || null
  const info = (balance.infos || [])[0] || null
  const refreshSec = Math.round((data.refreshMs || 60000) / 1000)

  // 分项合计：三档加起来就是本次进程的估算花费
  const items = [
    { label: '缓存未命中输入', value: usage.costCacheMiss || 0, color: 'var(--dsw-alias-brand-primary)' },
    { label: '输出 tokens', value: usage.costOutput || 0, color: 'var(--dsw-alias-state-business-primary)' },
    { label: '缓存命中输入', value: usage.costCacheHit || 0, color: 'var(--dsw-alias-state-success-primary)' },
  ]
  const maxItem = Math.max(1e-9, ...items.map((row) => row.value))

  const models = usage.models || []
  const days = usage.days || []
  const recent = usage.recent || []

  return h('div', { className: 'dab-page' },
    h('h3', { className: 'dab-h' }, 'DeepSeek API 余额与消耗'),
    h('p', { className: 'dab-sub' },
      '余额来自官方 /user/balance 接口；消耗由本机拦截每一次模型调用实时累计，按官方峰谷价折算。'),

    snap.error ? h('div', { className: 'dab-err' }, `最近一次读取失败：${snap.error}`) : null,
    balance.ok === false && balance.error ? h('div', { className: 'dab-err' }, `余额：${balance.error}`) : null,

    h('div', { className: 'dab-cards' },
      Card('账户余额', balance.ok ? fmtBalance(balance) : '—',
        info ? `充值 ${fmtMoney(info.toppedUpBalance, info.currency)} · 赠送 ${fmtMoney(info.grantedBalance, info.currency)}` : '未取到余额'),
      Card('本进程累计花费', fmtCost(usage.costTotal || 0, money), `估算值 · ${usage.calls || 0} 次调用`),
      Card('缓存命中率', fmtPct(usage.cacheHitRate || 0),
        `命中 ${fmtTokens(usage.cacheHitTokens)} / 未命中 ${fmtTokens(usage.cacheMissTokens)}`),
      Card('输出 tokens', fmtTokens(usage.outputTokens || 0),
        usage.reasoningTokens ? `含思维链 ${fmtTokens(usage.reasoningTokens)}` : '含思维链与正文'),
    ),

    h('div', { className: 'dab-sec' },
      h('h4', null, '钱花在哪里（按 token 类别拆分）'),
      ...items.map((row) => Bar(row.label, row.value, maxItem, row.color, (v) => fmtCost(v, money))),
      h('div', { className: 'dab-note' },
        `峰时花费 ${fmtCost(usage.costPeak || 0, money)}，谷时花费 ${fmtCost(usage.costOffPeak || 0, money)}。`,
        ' 官方峰时为 UTC 周一至周五 01:00-04:00 与 06:00-10:00，谷时单价为峰时的一半，所以同样的 token 在谷时更便宜。'),
    ),

    (usage.imageTokensEstimate > 0)
      ? h('div', { className: 'dab-sec' },
        h('h4', null, '图片消耗'),
        Bar('请求图片视觉 token（估算）', usage.imageTokensEstimate, Math.max(usage.imageTokensEstimate, 1), 'var(--dsw-alias-state-warn-primary)', fmtTokens),
        h('div', { className: 'dab-note' }, '按官方图片 token 计算器估算，已含在上面「缓存未命中输入」的实际计费里，此处仅作归因展示。'))
      : null,

    h('div', { className: 'dab-sec' },
      h('h4', null, '按模型'),
      models.length === 0
        ? h('div', { className: 'dab-note' }, '本进程还没有记录到模型调用。')
        : h('table', { className: 'dab-table' },
          h('thead', null, h('tr', null,
            h('th', null, '模型'), h('th', null, '调用'), h('th', null, '命中 token'),
            h('th', null, '未命中 token'), h('th', null, '输出 token'), h('th', null, '花费'))),
          h('tbody', null, ...models.map((row) => h('tr', { key: row.key },
            h('td', null, row.key),
            h('td', null, String(row.calls)),
            h('td', null, fmtTokens(row.cacheHitTokens)),
            h('td', null, fmtTokens(row.cacheMissTokens)),
            h('td', null, fmtTokens(row.outputTokens)),
            h('td', null, fmtCost(row.cost, money)),
          )))),
    ),

    h('div', { className: 'dab-sec' },
      h('h4', null, '按用途'),
      h('table', { className: 'dab-table' },
        h('thead', null, h('tr', null, h('th', null, '用途'), h('th', null, '调用'), h('th', null, '花费'))),
        h('tbody', null, ...(usage.purposes || []).map((row) => h('tr', { key: row.key },
          h('td', null, row.key === 'chat' ? '对话' : (row.key === 'compaction' ? '上下文压缩' : (row.key === 'session-title' ? '生成标题' : row.key))),
          h('td', null, String(row.calls)),
          h('td', null, fmtCost(row.cost, money)),
        )))),
    ),

    days.length > 0
      ? h('div', { className: 'dab-sec' },
        h('h4', null, '最近 14 天'),
        h('table', { className: 'dab-table' },
          h('thead', null, h('tr', null, h('th', null, '日期 (UTC)'), h('th', null, '调用'), h('th', null, '花费'))),
          h('tbody', null, ...days.map((row) => h('tr', { key: row.day },
            h('td', null, row.day), h('td', null, String(row.calls)), h('td', null, fmtCost(row.cost, money)),
          )))),
      )
      : null,

    recent.length > 0
      ? h('div', { className: 'dab-sec' },
        h('h4', null, '最近调用'),
        h('table', { className: 'dab-table' },
          h('thead', null, h('tr', null,
            h('th', null, '时间'), h('th', null, '模型'), h('th', null, '命中/未命中/输出'),
            h('th', null, '时段'), h('th', null, '花费'))),
          h('tbody', null, ...recent.map((row, index) => h('tr', { key: `${row.at}-${index}` },
            h('td', null, String(row.at).replace('T', ' ').slice(5, 19)),
            h('td', null, row.model),
            h('td', null, `${fmtTokens(row.cacheHitTokens)}/${fmtTokens(row.cacheMissTokens)}/${fmtTokens(row.outputTokens)}`),
            h('td', null, row.peak ? '峰' : '谷'),
            h('td', null, fmtCost(row.cost, money)),
          )))),
      )
      : null,

    h('div', { className: 'dab-sec' },
      h('h4', null, '价格表与控制'),
      h('div', { className: 'dab-note' },
        `价格表版本 ${pricing.version || '未知'} · 官方计价币种 ${pricing.currency || 'USD'} · 单位 ${pricing.unit || 'per_1m_tokens'}/百万 tokens`,
        pricing.overridden ? '（已被 config/pricing.json 覆盖）' : '（内置默认值）',
        h('br'),
        `来源：${pricing.source || '（未记录）'}`,
        h('br'),
        `花费展示币种：${money ? `${money.currency}（按 1 ${money.sourceCurrency || 'USD'} = ${money.rate} ${money.currency} 折算）` : '与官方计价币种一致'}；余额按接口返回币种原样显示，不参与折算。`,
        h('br'),
        `API key：${apiKey.configured ? `已配置（来源 ${apiKey.source}）` : '未配置，余额无法读取'}`,
        h('br'),
        `传输通道：${data.transport || 'unknown'} · 已记账 ${usage.calls || 0} 次调用 · 未识别模型计价 ${usage.unpricedCalls || 0} 次`,
      ),
      h('div', { className: 'dab-row', style: { marginTop: '12px' } },
        h('button', { className: 'dab-btn', disabled: snap.refreshing, onClick: () => { void load(true) } },
          snap.refreshing ? '刷新中…' : '立即刷新余额'),
        h('select', {
          className: 'dab-sel',
          value: String(data.refreshMs),
          onChange: (event) => { void callHost('setRefreshMs', { ms: Number(event.target.value) }) },
        },
        ...[15000, 30000, 60000, 300000].map((ms) => h('option', { key: ms, value: String(ms) },
          `每 ${ms >= 60000 ? `${ms / 60000} 分钟` : `${ms / 1000} 秒`}刷新`)),
        ),
        h('span', { className: 'dab-note', style: { margin: 0 } },
          `余额最近刷新：${fmtAgo(balance.at, data.now)}（定时刷新 ${refreshSec}s）`),
      ),
    ),
  )
}

// --- 输入框下方：本对话消费明细（点胶囊展开） -------------------------------

/**
 * 折叠在输入框下方的消费明细面板。
 * 数据来源仍是同一份 Host 快照：Host 按 sessionId 记账，这里用当前会话 id 过滤，
 * 所以「本对话花了多少」是**精确归因**，不是估算。
 */
function SessionPanel(props) {
  const [open, toggle] = usePanelOpen()
  const [snap, load] = useSnapshot(props.ctx, props.timer, open)
  try {
    return sessionPanelBody(props, open, toggle, snap, load)
  } catch (error) {
    return open
      ? h('div', { className: 'dab-dock' },
        h('div', { className: 'dab-err', style: { margin: 0 } },
          `消费面板渲染失败（已安全降级）：${String((error && error.message) || error)}`))
      : null
  }
}

function sessionPanelBody(props, open, toggle, snap, load) {
  if (!open) return null

  const closeButton = h('button', { className: 'dab-x', title: '收起', onClick: () => toggle(false) }, '×')

  if (!snap.data) {
    return h('div', { className: 'dab-dock' },
      h('div', { className: 'dab-dock-head' },
        h('b', null, '消费明细'), h('span', { className: 'sp' }), closeButton),
      h('div', { className: 'dab-note', style: { margin: 0 } },
        snap.loading ? '正在读取…' : `读取失败：${snap.error || '未知错误'}`),
    )
  }

  const data = snap.data
  const usage = data.usage || {}
  const balance = data.balance || {}
  const money = data.money || null
  const sessionId = String(props.sessionId || '')
  const mine = (usage.sessions || []).filter((row) => row.key === sessionId)[0] || null

  // 本对话没有可归因记录时（例如这个会话在插件启动前就开始了），退回本进程合计并说明。
  const scope = mine || {
    calls: usage.calls || 0,
    cost: usage.costTotal || 0,
    costCacheHit: usage.costCacheHit || 0,
    costCacheMiss: usage.costCacheMiss || 0,
    costOutput: usage.costOutput || 0,
    cacheHitTokens: usage.cacheHitTokens || 0,
    cacheMissTokens: usage.cacheMissTokens || 0,
    outputTokens: usage.outputTokens || 0,
    firstAt: 0,
    lastAt: 0,
  }

  const rows = sessionId
    ? (usage.recent || []).filter((row) => row.sessionId === sessionId).slice(0, 8)
    : []

  const items = [
    { label: '缓存未命中输入', value: scope.costCacheMiss || 0, color: 'var(--dsw-alias-brand-primary)' },
    { label: '输出 tokens', value: scope.costOutput || 0, color: 'var(--dsw-alias-state-business-primary)' },
    { label: '缓存命中输入', value: scope.costCacheHit || 0, color: 'var(--dsw-alias-state-success-primary)' },
  ]
  const maxItem = Math.max(1e-9, ...items.map((row) => row.value))

  return h('div', { className: 'dab-dock' },
    h('div', { className: 'dab-dock-head' },
      h('b', null, mine ? '本对话消费' : '本进程消费（本对话暂无可归因记录）'),
      h('span', { className: 'sp' }),
      h('span', { className: 'dab-note', style: { margin: 0 } },
        scope.lastAt ? `最近一次 ${fmtClock(scope.lastAt)}` : ''),
      h('button', {
        className: 'dab-btn',
        disabled: snap.refreshing,
        onClick: () => { void load(true) },
      }, snap.refreshing ? '刷新中…' : '刷新'),
      closeButton,
    ),

    h('div', { className: 'dab-mini' },
      mini('本对话花费', fmtCost(scope.cost, money)),
      mini('调用次数', `${scope.calls} 次`),
      mini('缓存命中率', fmtPct(hitRateOf(scope))),
      mini('输出 tokens', fmtTokens(scope.outputTokens)),
    ),

    ...items.map((row) => Bar(row.label, row.value, maxItem, row.color, (v) => fmtCost(v, money))),

    rows.length > 0
      ? h('table', { className: 'dab-table', style: { marginTop: '10px' } },
        h('thead', null, h('tr', null,
          h('th', null, '时间'), h('th', null, '模型'),
          h('th', null, '命中/未命中/输出'), h('th', null, '时段'), h('th', null, '花费'))),
        h('tbody', null, ...rows.map((row, index) => h('tr', { key: `${row.at}-${index}` },
          h('td', null, fmtClock(row.at)),
          h('td', null, row.model),
          h('td', null, `${fmtTokens(row.cacheHitTokens)}/${fmtTokens(row.cacheMissTokens)}/${fmtTokens(row.outputTokens)}`),
          h('td', null, row.peak ? '峰' : '谷'),
          h('td', null, fmtCost(row.cost, money)),
        ))))
      : null,

    h('div', { className: 'dab-note' },
      `余额 ${balance.ok ? fmtBalance(balance) : '—'} · 本进程合计 ${fmtCost(usage.costTotal || 0, money)}（${usage.calls || 0} 次调用）· 命中率 ${fmtPct(usage.cacheHitRate || 0)}`,
      h('br'),
      '这些数字是把 DSH 已经收到的 token 用量做本地算术得到的：不额外调用模型、不消耗任何额外 token。唯一的对外请求是余额查询本身。',
    ),
  )
}

function mini(key, value) {
  return h('div', { key }, h('div', { className: 'k' }, key), h('div', { className: 'v' }, value))
}

// ===========================================================================
// apply(ctx) 主体
// ===========================================================================

ctx.effect(() => insertStyles(ctx, CSS), 'dsh-api-balance: styles')

const slots = ctx.get('slots')
if (slots && typeof slots.inject === 'function' && typeof slots.register === 'function') {
  const timer = ctx.get('timer')

  // 1) 会话标题右侧的小胶囊：一眼看到余额，点一下强制刷新。
  slots.inject('conversation.session.header.utilities', () => slots.register(
    { name: 'conversation.session.header.utilities', id: 'dsh-api-balance', order: 40, label: 'API 余额' },
    () => h(BalancePill, { ctx, timer }),
  ))

  // 2) 输入框下方的消费明细：点标题栏的胶囊展开/收起，回答「这个对话花了多少」。
  slots.inject('conversation.composer.dock', () => slots.register(
    { name: 'conversation.composer.dock', id: 'dsh-api-balance', order: 30 },
    (slotProps) => h(SessionPanel, { ctx, timer, sessionId: slotProps && slotProps.sessionId }),
  ))

  // 3) 设置页里的完整仪表盘：回答「钱花在哪里」。
  slots.inject('settings.section', () => slots.register(
    { name: 'settings.section', id: 'dsh-api-balance', order: 60, label: 'API 余额与消耗' },
    () => h(Dashboard, { ctx, timer }),
  ))
}
