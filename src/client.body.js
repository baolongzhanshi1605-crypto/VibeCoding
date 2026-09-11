// ===========================================================================
// dsh-api-balance · Client 半（apply 函数体）
//
// 与 host.body.js 一样，本文件被 tools/build.mjs 内联成两种形态共用的函数体：
//   * 动态平面：cordis_define 的 code.client（浏览器内临时插件）
//   * 常驻平面：package/lib/client.js 的手写 __ModuleLoader__ 工厂
//
// 只能用：React.createElement（无 JSX）、ctx.get() 的服务、平台 builtin。
// UI 落点（两个都是 additive 的 list 槽，replaceRisk = none，不会遮挡原生界面）：
//   1. conversation.session.header.utilities —— 会话标题右侧的常驻小胶囊（点击立即刷新余额）；
//   2. settings.section                      —— 设置里的完整仪表盘页（回答「钱花在哪里」）。
//
// 交互模型刻意保持简单：胶囊只做「显示 + 刷新」，一切明细都在设置页里。
// （v0.2 曾在输入框下方加过一个展开面板，实测既难用又难维护，v0.4.1 已移除。）
// ===========================================================================

const ROUTE_PREFIX = '/dsh-api-balance'
/** 界面拉取快照的间隔：与宿主 5 秒刷新对齐，让「花了多少钱」有实时感。 */
const POLL_MS = 5000

/** 极简 createElement 包装，替代 JSX。 */
function h(type, props, ...children) {
  return React.createElement(type, props, ...children)
}

/**
 * Host RPC：动态平面走 host.call，常驻平面走同源 HTTP 路由。
 *
 * ⚠️ 常驻平面用 GET，所以参数必须编进 query string —— 早先这里直接 fetch 不带任何参数，
 * 宿主 handler 永远只收到 `{}`：诊断上报的内容全部丢失（clientDiag 里只有空字符串）。
 */
async function callHost(method, args) {
  if (typeof host !== 'undefined' && host && typeof host.call === 'function') {
    return host.call(method, args === undefined ? {} : args)
  }
  if (typeof fetch !== 'function') throw new Error('当前运行形态不支持 host.call，也没有 fetch')
  let url = `${ROUTE_PREFIX}/${method}`
  if (args && typeof args === 'object' && Object.keys(args).length > 0) {
    url += `?data=${encodeURIComponent(JSON.stringify(args))}`
  }
  const response = await fetch(url, { method: 'GET', cache: 'no-store' })
  if (!response.ok) throw new Error(`Host 接口 ${method} 返回 HTTP ${response.status}`)
  return response.json()
}

/**
 * 打开设置面板并切到本插件的分区。
 *
 * ⚠️ 先说清一个约束：**DSH 没有提供「打开设置」的服务**。
 * settings 面板的 `open` 与 `activeId` 是 `dsh-client-ui-settings-general` 里的
 * **组件局部 state**；唯一暴露 `openSection(id)` 的地方是 `settings.onboarding`
 * 步骤的 props，而那只在 onboarding 期间存在（只有 `onboardingStep !== undefined`
 * 时才渲染）。所以没有官方入口可走。
 *
 * 折中方案，全程 try/catch，最坏情况只是「点了没跳转」，绝不报错：
 *   1. 用 **ARIA 语义**找设置触发器 `[aria-haspopup="dialog"]` —— 这是可访问性契约，
 *      比 CSS module 生成的类名稳定得多；
 *   2. 面板渲染出来后再点**我们自己注册的那一行**（按我们自己的 label 文本找，
 *      找的是自己贡献的内容，不是产品界面元素）；
 *   3. 每一步都要求「恰好命中一个」才动手，否则放弃。
 *
 * @returns 是否成功跳转（失败时调用方回落成刷新余额）
 */
async function openSettingsSection(label) {
  try {
    if (typeof document === 'undefined' || typeof document.querySelectorAll !== 'function') return false
    const triggers = Array.from(document.querySelectorAll('button[aria-haspopup="dialog"], [aria-haspopup="dialog"]'))
    if (triggers.length === 0) return false
    const findRow = () => {
      const rows = Array.from(document.querySelectorAll('button, [role="tab"], [role="button"]'))
        .filter((node) => (node.textContent || '').trim() === label)
      return rows.length === 1 ? rows[0] : null
    }
    // 页面上可能不止一个 dialog 触发器：逐个试 —— 点开 → 找我们那一行 → 找到即成功。
    for (const trigger of triggers) {
      try {
        trigger.click()
      } catch {
        continue
      }
      for (let attempt = 0; attempt < 10; attempt += 1) {
        await new Promise((resolve) => {
          if (typeof setTimeout === 'function') setTimeout(resolve, 50)
          else resolve()
        })
        const row = findRow()
        if (row) {
          row.click()
          return true
        }
      }
    }
    return false
  } catch {
    return false
  }
}

/** 本插件在设置里的分区标题；必须与 slots.register 里的 label 完全一致。 */
const SETTINGS_SECTION_LABEL = 'API 余额与消耗'

/**
 * 把客户端侧的问题回传给宿主（宿主存进快照的 clientDiag）。
 *
 * 为什么需要：浏览器里的渲染异常在这边完全看不到 —— 没有 console、拿不到截图，
 * 只能靠人转述。有了它，`curl .../snapshot` 就能直接读到真实的异常文本与调用栈。
 * 上报本身失败绝不允许再抛（否则会把诊断变成第二个 bug）。
 */
function reportProblem(from, error, detail) {
  try {
    void callHost('report', {
      from,
      message: String((error && error.message) || error || ''),
      stack: String((error && error.stack) || ''),
      detail: detail === undefined ? '' : String(detail),
    })
  } catch {
    /* 忽略：诊断上报失败不构成功能问题 */
  }
}

/**
 * 注入样式表。
 *
 * 两个平面机制不同，这里都要覆盖：
 *   * 动态平面：求值器提供 `styles` builtin（styles.insert(css)）。
 *   * 常驻平面：**客户端没有 styles 服务**（服务目录只有 layout/locale/sessions/
 *     slots/theme/timer/uiWorkspace/workspaces），必须自己插一个 <style> 元素 ——
 *     官方 35 个客户端插件（dsh-client-ui-*）用的就是这个方式。
 *
 * ⚠️ 踩过的坑：早先这里只有「styles builtin → ctx.get('styles') → 返回空操作」，
 * 常驻平面两条都拿不到，于是 CSS **一行都没注入**：界面全是裸文本、胶囊退化成
 * 原生按钮方框，且没有任何报错。这是「静默降级掩盖功能缺失」的又一例。
 */
function insertStyles(ctx, css) {
  if (typeof styles !== 'undefined' && styles && typeof styles.insert === 'function') {
    return styles.insert(css)
  }
  const service = ctx.get('styles')
  if (service && typeof service.insert === 'function') return service.insert(css)
  if (typeof document === 'undefined' || !document.head) return () => {}
  const element = document.createElement('style')
  element.setAttribute('data-dsh-plugin', 'dsh-api-balance')
  element.textContent = css
  document.head.appendChild(element)
  return () => {
    try {
      element.remove()
    } catch {
      /* 已经被移除了 */
    }
  }
}

const CSS = `
.dab-pill{position:relative;display:inline-flex;align-items:center;gap:7px;height:28px;padding:0 11px;
  border:1px solid var(--dsw-alias-border-l1);border-radius:999px;background:transparent;
  color:var(--dsw-alias-label-primary);font-size:12px;line-height:1;cursor:pointer;
  font-variant-numeric:tabular-nums;white-space:nowrap;transition:background .12s ease,border-color .12s ease;
  pointer-events:auto;-webkit-app-region:no-drag;user-select:none;-webkit-user-select:none}
.dab-pill *{pointer-events:none;-webkit-app-region:no-drag;user-select:none;-webkit-user-select:none}
.dab-pill:hover{border-color:var(--dsw-alias-border-l2);background:var(--dsw-alias-interactive-bg-hover)}
.dab-pill:active{background:var(--dsw-alias-interactive-bg-active)}
.dab-amount{font-weight:600;letter-spacing:-.1px}
.dab-cost{color:var(--dsw-alias-label-tertiary)}
.dab-dot{width:6px;height:6px;border-radius:50%;flex:0 0 auto}
.dab-dot.ok{background:var(--dsw-alias-state-success-primary)}
.dab-dot.warn{background:var(--dsw-alias-state-warn-primary)}
.dab-dot.err{background:var(--dsw-alias-state-error-primary)}
.dab-page{padding:2px 2px 36px;color:var(--dsw-alias-label-primary);font-size:13px;line-height:1.5}
.dab-hero{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 6px}
.dab-hero .big{font-size:30px;font-weight:650;letter-spacing:-.6px;font-variant-numeric:tabular-nums}
.dab-hero .tag{font-size:11px;color:var(--dsw-alias-label-tertiary);
  border:1px solid var(--dsw-alias-border-l1);border-radius:999px;padding:3px 9px}
.dab-sub{color:var(--dsw-alias-label-tertiary);font-size:12px;margin:0 0 22px;max-width:660px;line-height:1.65}
.dab-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px;margin-bottom:22px}
.dab-card{border:1px solid var(--dsw-alias-border-l1);border-radius:12px;
  background:var(--dsw-alias-bg-layer-1);padding:12px 14px}
.dab-card .k{color:var(--dsw-alias-label-tertiary);font-size:11px;margin-bottom:7px}
.dab-card .v{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.3px}
.dab-card .n{color:var(--dsw-alias-label-tertiary);font-size:11px;margin-top:5px;line-height:1.5}
.dab-sec{margin:0 0 22px}
.dab-sec>h4{margin:0 0 11px;font-size:12px;font-weight:600;color:var(--dsw-alias-label-secondary);
  padding-bottom:6px;border-bottom:1px solid var(--dsw-alias-border-l1)}
.dab-stack{display:flex;height:10px;border-radius:999px;overflow:hidden;
  background:var(--dsw-alias-bg-layer-2);margin:2px 0 13px}
.dab-stack>i{display:block;height:100%}
.dab-legend{display:flex;flex-wrap:wrap;gap:8px 18px}
.dab-legend>div{display:flex;align-items:center;gap:7px;font-size:12px}
.dab-legend .sw{width:9px;height:9px;border-radius:3px;flex:0 0 auto}
.dab-legend .lb{color:var(--dsw-alias-label-secondary)}
.dab-legend .vl{font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-primary);font-weight:600}
.dab-legend .pc{color:var(--dsw-alias-label-tertiary);font-size:11px}
.dab-bar{display:grid;grid-template-columns:150px 1fr 96px;align-items:center;gap:12px;padding:5px 0;font-size:12px}
.dab-bar .t{color:var(--dsw-alias-label-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dab-bar .m{height:8px;border-radius:999px;background:var(--dsw-alias-bg-layer-2);overflow:hidden}
.dab-bar .m>i{display:block;height:100%;border-radius:999px}
.dab-bar .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--dsw-alias-label-primary)}
.dab-table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
.dab-table th{text-align:right;font-weight:500;color:var(--dsw-alias-label-tertiary);
  padding:6px 10px;border-bottom:1px solid var(--dsw-alias-border-l2);white-space:nowrap}
.dab-table th:first-child,.dab-table td:first-child{text-align:left}
.dab-table td{text-align:right;padding:6px 10px;border-bottom:1px solid var(--dsw-alias-border-l1);
  color:var(--dsw-alias-label-secondary)}
.dab-table tbody tr:hover td{background:var(--dsw-alias-interactive-bg-hover)}
.dab-table td:first-child{color:var(--dsw-alias-label-primary)}
.dab-table tr:last-child td{border-bottom:none}
.dab-note{margin-top:11px;color:var(--dsw-alias-label-tertiary);font-size:11px;line-height:1.7}
.dab-diag{display:inline-block;margin:0 0 14px;padding:5px 10px;border-radius:7px;font-size:11px;
  border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-tertiary);
  background:var(--dsw-alias-bg-layer-1)}
.dab-diag.bad{color:var(--dsw-alias-state-error-primary)}
.dab-err{margin:0 0 14px;padding:10px 12px;border-radius:9px;font-size:12px;line-height:1.6;
  border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-state-error-primary);
  background:var(--dsw-alias-bg-layer-1);word-break:break-all}
.dab-row{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.dab-btn{height:30px;padding:0 14px;border-radius:8px;font-size:12px;cursor:pointer;
  border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);
  color:var(--dsw-alias-label-primary);transition:background .12s ease}
.dab-btn:hover{background:var(--dsw-alias-interactive-bg-hover)}
.dab-btn:disabled{opacity:.5;cursor:default}
.dab-sel{height:30px;border-radius:8px;font-size:12px;padding:0 8px;
  border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);
  color:var(--dsw-alias-label-primary)}
`

// --- 展示层小工具（纯函数，Host/Client 同口径） -----------------------------

function pct(part, whole) {
  if (!whole) return 0
  return Math.max(0, Math.min(1, part / whole))
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
    // ⚠️ 定时器必须在**这里**解析，不能用注册时捕获的那个引用：
    // 常驻插件 apply 时 timer 服务可能还没就绪，捕获到的会是 undefined，
    // 结果就是「只请求一次、之后永不刷新」—— 胶囊会永久卡在启动那一瞬间的状态
    // （宿主首次读余额尚未完成 → 显示降级 → 再也回不来）。
    const timerService = (timer && typeof timer.interval === 'function')
      ? timer
      : (ctx && typeof ctx.get === 'function' ? ctx.get('timer') : undefined)
    let dispose = () => {}
    if (timerService && typeof timerService.interval === 'function') {
      dispose = timerService.interval(() => { void tick(false) }, POLL_MS)
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
  const [snap, load] = useSnapshot(props.ctx, props.timer, true)
  // 挂载后做一次**真实的命中测试**并把结果回传宿主。
  // 为什么需要：用户反馈「只有边缘能点」，而我在浏览器外面看不到 DOM，
  // 只有用 elementFromPoint 测出「胶囊中心点究竟命中了哪个元素」才能定位。
  React.useEffect(() => {
    try {
      const pill = document.querySelector('.dab-pill')
      const styleTags = document.querySelectorAll('style[data-dsh-plugin="dsh-api-balance"]')
      const hasNone = Array.from(styleTags).some((node) => String(node.textContent || '').includes('pointer-events:none'))
      let centerHit = 'n/a'
      const rect = pill && typeof pill.getBoundingClientRect === 'function' ? pill.getBoundingClientRect() : null
      if (rect && rect.width > 0 && typeof document.elementFromPoint === 'function') {
        const node = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
        centerHit = node ? `${node.tagName}.${String(node.className || '')}`.slice(0, 70) : 'null'
      }
      const triggers = document.querySelectorAll('button[aria-haspopup="dialog"], [aria-haspopup="dialog"]').length
      reportProblem(
        'pill-diagnose',
        null,
        `styleTags=${styleTags.length} hasNone=${hasNone} triggers=${triggers} w=${rect ? Math.round(rect.width) : -1} centerHit=${centerHit}`,
      )
    } catch (error) {
      reportProblem('pill-diagnose', error)
    }
  }, [])
  try {
    return pillBody(snap, load)
  } catch (error) {
    reportProblem('pill-render', error)
    return h('span', {
      className: 'dab-pill',
      title: `余额面板渲染失败（已安全降级）：${String((error && error.message) || error)}`,
    }, '余额 ✗')
  }
}

/** 胶囊渲染降级时的上报节流（同一状态最多每 5 秒报一次，避免刷爆宿主）。 */
let lastPillReportAt = 0

function pillBody(snap, load) {
  const data = snap.data
  const balance = data && data.balance
  const usage = (data && data.usage) || null
  // ⚠️ money 必须在这里声明：早先漏了这一行，下面 fmtCost(…, money) 会抛
  // ReferenceError，被 try/catch 吞掉后胶囊永远只显示「余额 —」。
  const money = (data && data.money) || null
  const pending = !!(balance && balance.pending)
  const status = !data || pending ? 'warn' : (balance && balance.ok ? 'ok' : 'err')

  // 没拿到数据 / 余额不可用时，把确切原因回传宿主，方便直接排查。
  if (!data || !balance || (balance.ok !== true && balance.pending !== true)) {
    const now = Date.now()
    if (now - lastPillReportAt > 5000) {
      lastPillReportAt = now
      reportProblem(
        'pill-state',
        snap.error || (balance && balance.error) || 'no-data',
        `hasData=${!!data} loading=${!!snap.loading} balanceOk=${balance ? balance.ok : 'n/a'}`,
      )
    }
  }

  const title = [
    balance && balance.ok ? `余额：${fmtBalance(balance)}` : `余额读取失败：${(balance && balance.error) || snap.error || '等待中'}`,
    usage ? `累计花费 ≈ ${fmtCost(usage.costTotal, money)}（${usage.calls} 次调用${usage.restored ? '，已跨重启累计' : ''}）` : '',
    usage ? `缓存命中率 ${fmtPct(usage.cacheHitRate)}` : '',
    data ? `刷新于 ${fmtAgo(balance && balance.at, data.now)}` : '',
    '',
    '点击打开设置里的明细（API 余额与消耗）；若跳转未生效则改为刷新余额',
  ].filter(Boolean).join('\n')

  return h('button', {
    className: 'dab-pill',
    type: 'button',
    title,
    onClick: () => {
      // 主行为：跳到设置里的本插件分区。跳转失败则回落成「刷新余额」，保证点击永远有用。
      void openSettingsSection(SETTINGS_SECTION_LABEL).then((jumped) => {
        if (!jumped) void load(true)
      })
    },
  },
  // 注意：这里**不再需要**透明命中层 —— CSS 里 `.dab-pill *{pointer-events:none}`
  // 让所有子元素都不吃事件，整颗胶囊（含文字与留白）都由 button 自己接住。
  h('span', { className: `dab-dot ${status}`, key: 'dot' }),
  h('span', { className: 'dab-amount', key: 'amount' },
    balance && balance.ok ? fmtBalance(balance) : (pending ? '余额 …' : '余额 ✗')),
  usage && usage.calls > 0
    ? h('span', { className: 'dab-cost', key: 'cost' }, `· ${fmtCost(usage.costTotal, money)}`)
    : null,
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
  const persistence = data.persistence || {}
  const backfill = data.backfill || null
  const info = (balance.infos || [])[0] || null
  const refreshSec = Math.round((data.refreshMs || 60000) / 1000)

  // 分项合计：三档加起来就是本次进程的估算花费
  const items = [
    { label: '缓存未命中输入', value: usage.costCacheMiss || 0, color: 'var(--dsw-alias-brand-primary)' },
    { label: '输出 tokens', value: usage.costOutput || 0, color: 'var(--dsw-alias-state-business-primary)' },
    { label: '缓存命中输入', value: usage.costCacheHit || 0, color: 'var(--dsw-alias-state-success-primary)' },
  ]
  const costSum = Math.max(1e-12, items.reduce((sum, row) => sum + row.value, 0))

  const models = usage.models || []
  const days = usage.days || []
  const recent = usage.recent || []

  return h('div', { className: 'dab-page' },
    // 自检行：把「客户端到底有没有拿到数据」直接写在界面上。
    // 加它是因为前端出问题时我这边看不到任何信息（页面日志、截图都拿不到），
    // 而这一行能让任何人一眼（或一句话）说清故障在哪一段。
    h('div', { className: `dab-diag${snap.error ? ' bad' : ''}` },
      snap.error
        ? `客户端自检：读取失败 — ${snap.error}`
        : `客户端自检：已连通（Host 传输 ${data.transport || '未知'} · 快照时间 ${new Date(data.now).toLocaleTimeString()}）`,
    ),

    // 顶部：一眼看到最重要的两个数字
    h('div', { className: 'dab-hero' },
      h('span', { className: 'big' }, balance.ok ? fmtBalance(balance) : '—'),
      h('span', { className: 'tag' }, balance.ok ? '账户余额' : '余额不可用'),
      h('span', { className: 'tag' }, `累计 ${fmtCost(usage.costTotal || 0, money)}`),
    ),
    h('p', { className: 'dab-sub' },
      '余额来自官方 /user/balance 接口；消耗由本机拦截每一次模型调用实时累计，按官方峰谷价折算。'),

    // 累计状态必须写清楚：否则「第一次记账从 0 开始」和「功能没生效」在界面上完全一样，
    // 用户会合理地以为坏了（这个误解真实发生过一次）。
    h('div', { className: 'dab-diag' },
      usage.restored
        ? `[累计 · 已恢复] 统计自 ${String(usage.since || '').replace('T', ' ').slice(0, 16)}（UTC）起 · 本次是第 ${usage.runs || 1} 次运行 · 重启后会接着往上加`
        : `[累计 · 首次记账] 磁盘上暂无更早的累计数据，从本次启动开始（第 ${usage.runs || 1} 次运行）· 从现在起每次重启都会接着累加`,
    ),

    snap.error ? h('div', { className: 'dab-err' }, `最近一次读取失败：${snap.error}`) : null,
    balance.ok === false && balance.error ? h('div', { className: 'dab-err' }, `余额：${balance.error}`) : null,

    h('div', { className: 'dab-cards' },
      Card('账户余额', balance.ok ? fmtBalance(balance) : '—',
        info ? `充值 ${fmtMoney(info.toppedUpBalance, info.currency)} · 赠送 ${fmtMoney(info.grantedBalance, info.currency)}` : '未取到余额'),
      Card('累计花费', fmtCost(usage.costTotal || 0, money),
        `估算值 · ${usage.calls || 0} 次调用${usage.restored ? ' · 已跨重启累计' : ''}`),
      Card('缓存命中率', fmtPct(usage.cacheHitRate || 0),
        `命中 ${fmtTokens(usage.cacheHitTokens)} / 未命中 ${fmtTokens(usage.cacheMissTokens)}`),
      Card('输出 tokens', fmtTokens(usage.outputTokens || 0),
        usage.reasoningTokens ? `含思维链 ${fmtTokens(usage.reasoningTokens)}` : '含思维链与正文'),
    ),

    h('div', { className: 'dab-sec' },
      h('h4', null, '钱花在哪里'),
      // 一条堆叠条 + 图例：比三行独立条形更能一眼看出比例
      h('div', { className: 'dab-stack' },
        ...items.filter((row) => row.value > 0).map((row) => h('i', {
          key: row.label,
          style: { width: `${(row.value / costSum) * 100}%`, background: row.color },
        })),
      ),
      h('div', { className: 'dab-legend' },
        ...items.map((row) => h('div', { key: row.label },
          h('span', { className: 'sw', style: { background: row.color } }),
          h('span', { className: 'lb' }, row.label),
          h('span', { className: 'vl' }, fmtCost(row.value, money)),
          h('span', { className: 'pc' }, fmtPct(row.value / costSum, 0)),
        )),
      ),
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
      h('h4', null, '累计数据与控制'),
      h('div', { className: 'dab-note' },
        `累计起始：${String(usage.since || '').replace('T', ' ').slice(0, 19)}（UTC） · 已运行 ${usage.runs || 1} 次 · ${usage.restored ? '本次已从磁盘恢复累计' : '本次未恢复（首次运行或文件不存在）'}`,
        h('br'),
        persistence.enabled
          ? `存储文件：${persistence.path}${persistence.savedAt ? `（最近写入 ${fmtAgo(persistence.savedAt, data.now)}）` : ''}`
          : `未启用持久化：${persistence.reason || '原因未知'}（累计只在本次运行内有效）`,
        persistence.error ? h('span', null, h('br'), `存储异常：${persistence.error}`) : null,
      ),

      // 回填：从 DSH 历史会话日志重建累计（读 event.data.usage）。
      h('div', { className: 'dab-row', style: { marginTop: '10px' } },
        h('button', {
          className: 'dab-btn',
          disabled: snap.refreshing || !!(backfill && backfill.inFlight),
          onClick: () => { void callHost('backfill').then(() => load(false)) },
        }, '回填历史消耗'),
        h('span', { className: 'dab-note', style: { margin: 0 } },
          '从 DSH 历史会话日志重建累计（先清空再按日志回放，可重复执行、不会重复计算）'),
      ),
      backfill
        ? h('div', { className: 'dab-note' },
          backfill.ok
            ? `回填成功：扫描 ${backfill.sessionsScanned}/${backfill.sessionCount} 个会话 → 命中 ${backfill.matched} 次带用量的调用${backfill.unpriced ? `（其中 ${backfill.unpriced} 次模型未识别、按兜底价计）` : ''} · 跳过本次新产生 ${backfill.skippedRecent || 0} 条${backfill.readEventsFailed ? ` · 读事件失败 ${backfill.readEventsFailed} 个会话` : ''} · 耗时 ${((backfill.elapsedMs || 0) / 1000).toFixed(1)}s · ${fmtAgo(backfill.at, data.now)}`
            : h('span', null,
              `回填未成功：${backfill.error}`,
              h('br'),
              `诊断：会话数=${backfill.sessionCount === undefined ? '?' : backfill.sessionCount} · 缺 id 的会话=${backfill.sessionsWithoutId === undefined ? '?' : backfill.sessionsWithoutId} · 读事件失败=${backfill.readEventsFailed === undefined ? '?' : backfill.readEventsFailed}`,
              h('br'),
              `字段结构：会话=${backfill.firstSessionKeys || '?'} · 会话头=${backfill.firstHeaderKeys || '?'} · 事件=${backfill.firstEventKeys || '?'}`,
            ),
        )
        : h('div', { className: 'dab-note' },
          '提示：v0.6.0 之前的消耗只存在内存里、没有落盘，所以那个时间段的数字找不回来；用这个按钮可以从会话日志重建**全部历史**。'),
      h('div', { className: 'dab-row', style: { marginTop: '12px' } },
        h('button', { className: 'dab-btn', disabled: snap.refreshing, onClick: () => { void load(true) } },
          snap.refreshing ? '刷新中…' : '立即刷新余额'),
        h('button', {
          className: 'dab-btn',
          disabled: snap.refreshing,
          onClick: () => { void callHost('resetLedger').then(() => load(false)) },
        }, '重置累计'),
        h('select', {
          className: 'dab-sel',
          value: String(data.refreshMs),
          onChange: (event) => { void callHost('setRefreshMs', { ms: Number(event.target.value) }) },
        },
        ...[5000, 15000, 60000, 300000].map((ms) => h('option', { key: ms, value: String(ms) },
          `每 ${ms >= 60000 ? `${ms / 60000} 分钟` : `${ms / 1000} 秒`}刷新`)),
        ),
        h('span', { className: 'dab-note', style: { margin: 0 } },
          `余额最近刷新：${fmtAgo(balance.at, data.now)}（定时刷新 ${refreshSec}s）`),
      ),
      h('div', { className: 'dab-note', style: { marginTop: '6px' } },
        `价格表：版本 ${pricing.version || '未知'} · 官方计价 ${pricing.currency || 'USD'}/${pricing.unit || 'per_1m_tokens'} · 来源 ${pricing.source || '未记录'}`,
        h('br'),
        `花费展示币种：${money ? `${money.currency}（按 1 ${money.sourceCurrency || 'USD'} = ${money.rate} ${money.currency} 折算）` : '与官方计价币种一致'}；余额按接口返回币种原样显示，不参与折算。`,
        h('br'),
        `API key：${apiKey.configured ? `已配置（来源 ${apiKey.source}）` : '未配置，余额无法读取'} · 传输通道：${data.transport || 'unknown'} · 未识别模型计价 ${usage.unpricedCalls || 0} 次`,
      ),
    ),
  )
}


// ===========================================================================
// apply(ctx) 主体
// ===========================================================================

ctx.effect(() => insertStyles(ctx, CSS), 'dsh-api-balance: styles')

/**
 * 把两处 UI 注册进 Slot。
 *
 * ⚠️ 关键教训：**常驻平面里 apply 跑得比 slots 服务注册更早**。
 * 早先这里写的是 `const slots = ctx.get('slots'); if (slots) {…}` ——
 * 拿不到就什么都不注册，而且一声不响：宿主侧一切正常，界面上却空无一物。
 * 现在用 ctx.inject 等 slots 就绪（官方客户端插件同样导出 inject = ["sessions","slots"]）。
 */
function registerContributions(ownerCtx) {
  const slots = ownerCtx.get('slots')
  if (!slots || typeof slots.inject !== 'function' || typeof slots.register !== 'function') return false
  const timer = ownerCtx.get('timer')

  // 1) 会话标题右侧的小胶囊：一眼看到余额与本次进程花费，点击立即刷新。
  slots.inject('conversation.session.header.utilities', () => slots.register(
    { name: 'conversation.session.header.utilities', id: 'dsh-api-balance', order: 40, label: 'API 余额' },
    () => h(BalancePill, { ctx: ownerCtx, timer }),
  ))

  // 2) 设置页里的完整仪表盘：回答「钱花在哪里」。
  slots.inject('settings.section', () => slots.register(
    { name: 'settings.section', id: 'dsh-api-balance', order: 60, label: SETTINGS_SECTION_LABEL },
    () => h(Dashboard, { ctx: ownerCtx, timer }),
  ))

  return true
}

// 动态平面：服务此时已就绪，直接注册。常驻平面：等服务出现再注册。
if (!registerContributions(ctx) && typeof ctx.inject === 'function') {
  ctx.inject(['slots'], (svcCtx) => { registerContributions(svcCtx) })
}
