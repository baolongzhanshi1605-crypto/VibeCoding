// ===========================================================================
// dsh-api-balance · Host 半（apply 函数体）
//
// 这个文件的内容会被 tools/build.mjs 原样内联，成为两种运行形态共用的同一个
// 函数体（见 docs/TECHNICAL.md「一份源码、两个平面」）：
//   * 动态平面：cordis_define 的 code.host（进程内临时插件）
//   * 常驻平面：package/lib/index.js 里 export function apply(ctx) { ... }
//
// 因此本文件里**不允许**出现 import / require / TypeScript / JSX，
// 只能使用：core/* 里的纯函数 + ctx.get() 拿到的服务 + 平台 builtin。
//
// 数据来源三件事：
//   1. 余额 —— credentials 取 DEEPSEEK_API_KEY，subprocess 起 curl 打官方余额接口；
//   2. 用量 —— 监听 llm/stream 瀑布，逐次调用累计 TokenUsage；
//   3. 计费 —— core/pricing.js 的峰谷价格表把 token 折算成钱。
// ===========================================================================

const ROUTE_PREFIX = '/dsh-api-balance'
const REFRESH_MS_DEFAULT = 60000
const BALANCE_MIN_INTERVAL_MS = 5000

/** 进程内全量状态。只存标量与小对象，绝不持有 DSH 的 live 对象。 */
const state = {
  startedAt: Date.now(),
  transport: 'none',
  refreshMs: REFRESH_MS_DEFAULT,
  pricing: PRICING_DEFAULT,
  pricingOverridden: false,
  ledger: createLedger(),
  /** 花费的展示币种与汇率。账本以美元记账，只在展示层折算（见 core/format.js）。 */
  money: DEFAULT_MONEY,
  balance: { ok: false, at: 0, error: '尚未刷新' },
  apiKey: { configured: false, source: 'unknown' },
  lastRefreshAt: 0,
  refreshInFlight: null,
}

// --- 传输层：动态 Package 用 harness RPC，常驻插件用 webServer 路由 ---------

/**
 * 把一组 host 方法暴露给 Client 半。
 * 两个平面用不同机制，但 handler 签名完全一致：async (args) => json。
 * @returns 'dsh-package-rpc' | 'http-route' | 'none'
 */
function installTransport(ctx, handlers) {
  const names = Object.keys(handlers)

  // 平面 A：动态 Cordis Package —— harness 是求值器提供的 builtin。
  if (typeof harness !== 'undefined' && harness && typeof harness.handle === 'function') {
    for (const name of names) harness.handle(name, handlers[name])
    return 'dsh-package-rpc'
  }

  // 平面 B：常驻插件 —— 复用 harness 自己的 HTTP 载体，同源、无需 typert/Remote。
  const webServer = ctx.get('webServer')
  if (!webServer || typeof webServer.register !== 'function') return 'none'
  for (const name of names) {
    const route = {
      kind: 'exact',
      path: `${ROUTE_PREFIX}/${name}`,
      handler: async (req, res) => {
        let payload
        try {
          payload = JSON.stringify(await handlers[name]({}))
        } catch (error) {
          payload = JSON.stringify({ ok: false, error: String((error && error.message) || error) })
          try {
            res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' })
            res.end(payload)
          } catch { /* 连接已断开，忽略 */ }
          return
        }
        try {
          res.writeHead(200, {
            'content-type': 'application/json; charset=utf-8',
            'cache-control': 'no-store',
          })
          res.end(payload)
        } catch { /* 连接已断开，忽略 */ }
      },
    }
    ctx.effect(() => webServer.register(route))
  }
  return 'http-route'
}

// --- 余额 -------------------------------------------------------------------

/** 从 credentials 服务解析 API key。返回值只在内存里用，绝不进入快照/日志。 */
async function readApiKey(ctx) {
  const credentials = ctx.get('credentials')
  if (!credentials || typeof credentials.resolve !== 'function') {
    return { ok: false, error: 'credentials 服务不可用' }
  }
  try {
    const resolved = await credentials.resolve(API_KEY_REF)
    if (!resolved || !resolved.value) {
      return { ok: false, error: `${API_KEY_REF} 未配置（可在 设置 → 模型 里填入）` }
    }
    return { ok: true, value: resolved.value, source: String(resolved.source || 'unknown') }
  } catch (error) {
    return { ok: false, error: `读取凭据失败：${String((error && error.message) || error)}` }
  }
}

/** 目录名（用作子进程 cwd）。不依赖 process/os 等宿主全局。 */
function dirnameOf(filePath) {
  const text = String(filePath || '')
  const cut = Math.max(text.lastIndexOf('\\'), text.lastIndexOf('/'))
  return cut > 0 ? text.slice(0, cut) : '.'
}

function readCollected(handle, which) {
  const reader = handle && handle.collected ? handle.collected[which] : undefined
  if (!reader || typeof reader.readFrom !== 'function') return ''
  try {
    return String(reader.readFrom(0).text || '')
  } catch {
    return ''
  }
}

/**
 * 调用官方余额接口。
 * API key 只出现在 curl 的 --config（走 stdin），不进 argv、不落盘、不进日志。
 */
async function fetchBalance(ctx) {
  const subprocess = ctx.get('subprocess')
  if (!subprocess || typeof subprocess.spawn !== 'function') {
    return { ok: false, at: Date.now(), error: 'subprocess 服务不可用，无法发起网络请求' }
  }
  const key = await readApiKey(ctx)
  state.apiKey = { configured: key.ok === true, source: key.source || 'none' }
  if (!key.ok) return { ok: false, at: Date.now(), error: key.error }

  const built = buildCurlConfig(key.value)
  if (!built.ok) return { ok: false, at: Date.now(), error: built.error }

  let executable
  try {
    executable = await subprocess.resolveExecutable('curl.exe')
  } catch (error) {
    return { ok: false, at: Date.now(), error: `找不到 curl.exe：${String((error && error.message) || error)}` }
  }

  let handle
  try {
    handle = subprocess.spawn({
      argv: [executable, '--silent', '--show-error', '--max-time', '20', '--config', '-'],
      cwd: dirnameOf(executable),
      stdio: {
        stdin: { data: built.config },
        stdout: { maxBytes: 262144 },
        stderr: { maxBytes: 16384 },
      },
      graceMs: 3000,
    })
  } catch (error) {
    return { ok: false, at: Date.now(), error: `启动 curl 失败：${String((error && error.message) || error)}` }
  }

  let outcome
  try {
    outcome = await handle.done
  } catch (error) {
    return { ok: false, at: Date.now(), error: `curl 执行失败：${String((error && error.message) || error)}` }
  }

  if (outcome && outcome.exitCode !== 0) {
    return { ok: false, at: Date.now(), error: describeCurlFailure(outcome.exitCode, readCollected(handle, 'stderr')) }
  }
  const parsed = parseBalance(readCollected(handle, 'stdout'))
  return { ...parsed, at: Date.now() }
}

/** 刷新余额；带最小间隔与并发合流，避免 UI 轮询打爆接口。 */
async function refreshBalance(ctx, force) {
  const now = Date.now()
  if (state.refreshInFlight) return state.refreshInFlight
  if (!force && state.balance.ok && now - state.lastRefreshAt < BALANCE_MIN_INTERVAL_MS) return state.balance
  state.refreshInFlight = (async () => {
    try {
      const next = await fetchBalance(ctx)
      // 失败时保留上一次的成功值，只在 error 字段体现，避免 UI 数字闪成 “—”。
      if (next.ok) {
        state.balance = next
        state.lastRefreshAt = Date.now()
      } else {
        state.balance = { ...state.balance, ok: false, error: next.error, at: state.balance.at }
        state.lastRefreshAt = Date.now()
      }
    } catch (error) {
      state.balance = { ...state.balance, ok: false, error: String((error && error.message) || error) }
    } finally {
      state.refreshInFlight = null
    }
    return state.balance
  })()
  return state.refreshInFlight
}

// --- 用量与计费 -------------------------------------------------------------

/** 用官方图片 token 计算器估算本次请求的视觉 token（仅作展示，不重复计费）。 */
function estimateImageTokens(ctx, options) {
  try {
    const llm = ctx.get('llm')
    if (!llm || typeof llm.imageRequestPricing !== 'function') return 0
    const images = []
    const messages = Array.isArray(options && options.messages) ? options.messages : []
    for (const message of messages) {
      const content = message && Array.isArray(message.content) ? message.content : []
      for (const block of content) {
        if (block && block.type === 'image' && block.attachment) images.push(block.attachment)
      }
    }
    if (images.length === 0) return 0
    const pricing = llm.imageRequestPricing(options.provider, options.model)
    if (!pricing || typeof pricing.priceImages !== 'function') return 0
    const rows = pricing.priceImages(images) || []
    let total = 0
    for (const row of rows) total += Number(row && row.visualTokens) || 0
    return total
  } catch {
    return 0
  }
}

/**
 * 包住一次模型调用流：原样转发每一个 chunk，只在最后把 usage 记进账本。
 * 用 try/finally 保证「消费方提前 break / 抛错 / 被 abort」时也会记账，
 * 并且绝不吞掉异常（不写 catch，只写 finally）。
 */
async function* tapModelStream(ctx, options, inner, imageTokensEstimate) {
  let usage = null
  let failed = false
  try {
    for await (const chunk of inner) {
      if (chunk) {
        if (chunk.type === 'usage' && chunk.usage) usage = chunk.usage
        else if (chunk.type === 'finish' && chunk.reason && chunk.reason.kind === 'error') failed = true
      }
      yield chunk
    }
  } finally {
    try {
      const at = new Date()
      const cost = costOfUsage(state.pricing, options && options.model, usage || {}, at)
      recordCall(state.ledger, {
        at,
        model: cost.model,
        provider: String((options && options.provider) || ''),
        purpose: String((options && options.purpose) || 'chat'),
        sessionId: String((options && options.sessionId) || ''),
        usage: usage || {},
        cost,
        imageTokensEstimate,
        ok: !failed,
      })
    } catch (error) {
      // 记账失败绝不能影响模型调用本身。
      console.error('[dsh-api-balance] 记账失败：', String((error && error.message) || error))
    }
  }
}

// --- 对外快照 ---------------------------------------------------------------

function buildSnapshot() {
  return {
    ok: true,
    transport: state.transport,
    now: Date.now(),
    startedAt: state.startedAt,
    refreshMs: state.refreshMs,
    apiKey: { configured: state.apiKey.configured, source: state.apiKey.source },
    balance: {
      ok: state.balance.ok === true,
      at: state.balance.at || 0,
      error: state.balance.error ? String(state.balance.error) : null,
      isAvailable: state.balance.isAvailable !== false,
      infos: Array.isArray(state.balance.infos) ? state.balance.infos : [],
    },
    usage: summarize(state.ledger, { topN: 25 }),
    money: {
      currency: state.money.currency,
      rate: state.money.rate,
      sourceCurrency: state.money.sourceCurrency,
      note: state.money.note,
    },
    pricing: {
      version: state.pricing.version,
      source: state.pricing.source,
      currency: state.pricing.currency,
      unit: state.pricing.unit,
      overridden: state.pricingOverridden,
      models: Object.keys(state.pricing.models || {}),
    },
  }
}

// ===========================================================================
// apply(ctx) 主体
// ===========================================================================

state.transport = installTransport(ctx, {
  snapshot: async () => buildSnapshot(),
  refresh: async () => {
    await refreshBalance(ctx, true)
    return buildSnapshot()
  },
  setRefreshMs: async (args) => {
    const next = Number(args && args.ms)
    if (Number.isFinite(next) && next >= 10000 && next <= 3600000) state.refreshMs = next
    return { ok: true, refreshMs: state.refreshMs }
  },
})

// 监听每一次模型调用（含子代理、压缩、标题生成），累计用量。
ctx.on('llm/stream', (options, next) => {
  let inner
  try {
    inner = next()
  } catch (error) {
    // next() 同步抛错时不能改变原有行为，原样抛出。
    throw error
  }
  const imageTokensEstimate = estimateImageTokens(ctx, options)
  return tapModelStream(ctx, options, inner, imageTokensEstimate)
})

// 定时刷新余额。用 timer 服务并交给 fiber 托管，插件停止/更新时自动清理。
const timer = ctx.get('timer')
if (timer && typeof timer.interval === 'function') {
  ctx.effect(() => timer.interval(() => { void refreshBalance(ctx, false) }, state.refreshMs))
}

// 首次启动异步拉一次；失败也不抛，交给 UI 显示错误。
void refreshBalance(ctx, true)
