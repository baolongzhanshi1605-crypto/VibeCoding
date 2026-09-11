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
/** 余额刷新间隔：默认 5 秒（用户要求「实时感」，可在设置页里改）。 */
const REFRESH_MS_DEFAULT = 5000
/** 最小刷新间隔，防止 UI 疯狂轮询把接口打爆。 */
const BALANCE_MIN_INTERVAL_MS = 3000

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
  /**
   * 客户端回传的诊断（见 handlers.report）。
   * 为什么需要它：浏览器里的渲染异常我这边完全看不到（拿不到 console、拿不到截图），
   * 于是让客户端把错误 POST 回宿主、存进快照，我就能直接读出来，不必靠人转述。
   */
  clientDiag: null,
  /**
   * 账本持久化：累计数字要活过重启。
   * `__storage` 由 build.mjs 在包装层注入 —— 常驻平面是 node:fs 异步桥，
   * 动态平面是 null（受限求值器没有模块系统），此时自动退化为「仅内存」。
   */
  storage: typeof __storage === 'undefined' ? null : __storage,
  ledgerDirty: false,
  ledgerSavedAt: 0,
  ledgerError: null,
  /** 回填状态（设置页「回填历史消耗」的结果），也是 in-flight 去重标志。 */
  backfill: null,
  backfillInFlight: false,
}

// --- 累计数据的读写 ---------------------------------------------------------

/** 从磁盘装载累计数据；失败只记录原因，绝不影响插件可用性。 */
async function loadPersistedLedger() {
  const storage = state.storage
  if (!storage || storage.enabled !== true) return
  try {
    const text = await storage.read()
    if (!text) return
    const parsed = JSON.parse(text)
    if (importLedger(state.ledger, parsed)) {
      state.ledger.runs = (state.ledger.runs || 0) + 1
    } else {
      state.ledgerError = '账本文件版本不认识，已忽略（保留原文件，不覆盖）'
      return
    }
    state.ledgerDirty = true
  } catch (error) {
    state.ledgerError = `读取账本失败：${String((error && error.message) || error)}`
  }
}

/** 把累计数据落盘（仅在有改动时）。失败只记录，绝不抛。 */
async function flushLedger(force) {
  const storage = state.storage
  if (!storage || storage.enabled !== true) return
  if (!force && !state.ledgerDirty) return
  try {
    const ok = await storage.write(JSON.stringify(exportLedger(state.ledger)))
    if (ok) {
      state.ledgerDirty = false
      state.ledgerSavedAt = Date.now()
      state.ledgerError = null
    } else {
      state.ledgerError = '写入账本失败（磁盘或权限问题）'
    }
  } catch (error) {
    state.ledgerError = `写入账本失败：${String((error && error.message) || error)}`
  }
}

/** 清空累计数据（设置页的「重置累计」）。 */
function resetLedger() {
  state.ledger = createLedger()
  state.ledgerDirty = true
  state.ledgerError = null
}

/**
 * 从 DSH 历史会话日志回填累计消耗。
 *
 * 数据来源是**官方的 `sessionQuery` 服务**，不是手工解压 `session.jsonl.zstd`
 * （那是 append-only 的多帧 zstd，普通解压只吃第一帧，实测解出来是 0 字节）。
 *
 * 服务契约（读自 `@deepseek-ai/dsh-session-query` 的实现，不是猜的）：
 *   * `listSessions()` → `[{ header: { id, createdAt, ... }, live, persisted }]`（新→旧）
 *   * `readSession(id)` → `{ session: header, inheritedEventCount, events }`，events 是
 *     **完整原始事件流**（`snapshotSessionEvent` = `structuredClone` + 冻结）
 *   * `listEvents(id)`  → 只有 `{ sessionId, seq, type, time, surface }` 轻量记录，**没有 `data`**，
 *     所以它永远取不到 `usage` —— 这条弯路走过一次，见 §5.12。
 *
 * 用量字段与官方 `dsh-session-stats` 完全一致，所以不靠猜结构：
 *   * `event.data.usage`                            —— 该次模型调用的 token 用量
 *   * `event.data.message.source.{provider,model}`  —— 哪条路由、哪个模型
 *   * `event.time`                                  —— 调用发生时刻（用于峰谷判定）
 *
 * 语义是**重建**而不是追加：先收集、确认有料之后才清空并回放。因此
 *   ① 可以重复执行、结果一致；② 不会与当前进程已经记下的账重复计算；
 *   ③ 读不到任何东西时**一个字节都不改**。
 */
async function backfillFromSessions(ctx) {
  const sessionQuery = ctx.get('sessionQuery')
  if (!sessionQuery || typeof sessionQuery.listSessions !== 'function') {
    return { ok: false, error: 'sessionQuery 服务不可用，无法读取历史会话' }
  }
  if (typeof sessionQuery.readSession !== 'function' && typeof sessionQuery.readSurface !== 'function') {
    return { ok: false, error: 'sessionQuery 既不支持 readSession 也不支持 readSurface，无法读取完整事件流' }
  }

  const rawSessions = (await sessionQuery.listSessions()) || []
  const sessions = Array.isArray(rawSessions) ? rawSessions : []
  const firstSessionKeys = sessions[0] && typeof sessions[0] === 'object' ? Object.keys(sessions[0]).join(',') : 'none'
  const firstHeaderKeys =
    sessions[0] && sessions[0].header && typeof sessions[0].header === 'object'
      ? Object.keys(sessions[0].header).join(',')
      : 'none'

  // 会话 id 在 `record.header.id`，不在记录本身 —— 记录形状是 `{ header, live, persisted }`。
  // 这是被真实数据教会的第二次：早期版本读 `session.id`，15 个会话**全部**拿不到 id，
  // 于是「一条用量都读不出来」却完全看不出原因。保留旧字段名做兜底以防上游改形状。
  const idOf = (record) => {
    if (!record || typeof record !== 'object') return ''
    const header = record.header && typeof record.header === 'object' ? record.header : null
    const candidates = [header && header.id, record.id, record.sessionId, record.sessionID]
    for (const candidate of candidates) {
      if (typeof candidate === 'string' && candidate) return candidate
    }
    return ''
  }

  // 读完整原始事件流。**不能用 `listEvents`**：它返回的是轻量记录
  // `{ sessionId, seq, type, time, surface }`，里面**没有 `data`**，永远取不到 `usage`。
  // 完整事件（含 `data.usage` / `data.message.source`）只有 readSession / readSurface 给。
  const readEventsOf = async (id) => {
    if (typeof sessionQuery.readSession === 'function') {
      const loaded = await sessionQuery.readSession(id)
      return loaded && Array.isArray(loaded.events) ? loaded.events : []
    }
    const loaded = await sessionQuery.readSurface(id)
    return loaded && Array.isArray(loaded.events) ? loaded.events : []
  }

  // 阶段一：**只收集，不动账本**。
  // 这是被真实事故教会的：早先版本先 reset 再扫描，结果一次「扫描到 0 条」就把用户
  // 已经累计的数据清空了。现在读不到任何东西就原样返回，绝不破坏既有数据。
  const entries = []
  let sessionsWithoutId = 0
  let readEventsFailed = 0
  let firstEventKeys = 'none'

  for (const record of sessions) {
    const id = idOf(record)
    if (!id) {
      sessionsWithoutId += 1
      continue
    }
    let events
    try {
      events = await readEventsOf(id)
    } catch {
      readEventsFailed += 1
      continue
    }
    if (!Array.isArray(events)) continue
    if (firstEventKeys === 'none' && events[0] && typeof events[0] === 'object') {
      firstEventKeys = Object.keys(events[0]).join(',')
    }
    for (const event of events) {
      const data = event && event.data
      const usage = data && data.usage
      if (!usage || typeof usage !== 'object') continue
      entries.push({ event, data, usage, id })
    }
  }

  if (entries.length === 0) {
    // 关键：不重置、不写盘，把探测到的真实结构报出来供排查。
    return {
      ok: false,
      error: '没有从会话日志里读到任何带用量的记录（已保留原有累计数据，未做任何修改）',
      sessionCount: sessions.length,
      sessionsWithoutId,
      readEventsFailed,
      firstSessionKeys,
      firstHeaderKeys,
      firstEventKeys,
    }
  }

  // 阶段二：确认有东西可写，才开始重建。
  resetLedger()
  // 清空的那一刻作为分界线：只回放这之前的日志。之后的调用由 llm/stream 实时记账，
  // 若日志里也已存在又被回放一次就会重复计算 —— 这个守卫把那个窗口关掉。
  const resetAt = Date.now()
  let matched = 0
  let unpriced = 0
  let skippedRecent = 0

  for (const entry of entries) {
    const eventTime = typeof (entry.event && entry.event.time) === 'number' ? entry.event.time : 0
    if (eventTime >= resetAt) {
      skippedRecent += 1
      continue
    }
    const source = entry.data && entry.data.message && entry.data.message.source
    const at = new Date(eventTime || Date.now())
    const cost = costOfUsage(state.pricing, source && source.model, entry.usage, at)
    recordCall(state.ledger, {
      at,
      model: cost.model,
      provider: String((source && source.provider) || ''),
      purpose: String((entry.data && entry.data.purpose) || 'chat'),
      sessionId: String(entry.id),
      usage: entry.usage,
      cost,
      ok: true,
    })
    matched += 1
    if (!cost.known) unpriced += 1
  }

  state.ledger.backfilledAt = Date.now()
  state.ledgerDirty = true
  await flushLedger(true)
  return {
    ok: true,
    sessionCount: sessions.length,
    sessionsScanned: sessions.length - sessionsWithoutId,
    sessionsWithoutId,
    readEventsFailed,
    matched,
    unpriced,
    skippedRecent,
    firstSessionKeys,
    firstHeaderKeys,
  }
}

// --- 传输层：动态 Package 用 harness RPC，常驻插件用 webServer 路由 ---------

/**
 * 真正把路由挂到 webServer 上。抽成独立函数的原因见 installTransport。
 */
function registerHttpRoutes(ownerCtx, names, handlers) {
  const webServer = ownerCtx.get('webServer')
  if (!webServer || typeof webServer.register !== 'function') return false
  for (const name of names) {
    const route = {
      kind: 'exact',
      path: `${ROUTE_PREFIX}/${name}`,
      handler: async (req, res) => {
        // 从 query string 里取客户端传参（常驻客户端用 GET，args 编码在 ?data= 上）。
        // 用最朴素的字符串处理而不是 URL 构造器，避免依赖任何宿主全局。
        let args = {}
        try {
          const rawUrl = String((req && req.url) || '')
          const marker = rawUrl.indexOf('data=')
          if (marker >= 0) {
            const raw = decodeURIComponent(rawUrl.slice(marker + 5).split('&')[0])
            const parsed = JSON.parse(raw)
            if (parsed && typeof parsed === 'object') args = parsed
          }
        } catch {
          args = {}
        }
        let payload
        try {
          payload = JSON.stringify(await handlers[name](args))
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
    ownerCtx.effect(() => webServer.register(route))
  }
  return true
}

/**
 * 把一组 host 方法暴露给 Client 半。
 * 两个平面用不同机制，但 handler 签名完全一致：async (args) => json。
 *
 * ⚠️ 关键教训：**常驻平面里 apply 跑得比 webServer 注册更早**。
 * 早先这里直接 ctx.get('webServer')，拿到 undefined 就返回 'none' ——
 * 结果是「插件装上了、也在插件树里，但一条路由都没挂」：后端 404、界面全空，
 * 而且没有任何报错。现在改成用 ctx.inject 等 webServer 就绪再挂。
 * （动态平面没这个问题：动态包是在整个系统启动完成之后才求值的。）
 *
 * @returns 'dsh-package-rpc' | 'http-route' | 'http-route-pending' | 'none'
 */
function installTransport(ctx, handlers) {
  const names = Object.keys(handlers)

  // 平面 A：动态 Cordis Package —— harness 是求值器提供的 builtin，服务此时一定已就绪。
  if (typeof harness !== 'undefined' && harness && typeof harness.handle === 'function') {
    for (const name of names) harness.handle(name, handlers[name])
    return 'dsh-package-rpc'
  }

  // 平面 B：常驻插件 —— 用 Cordis 官方等待语义等 webServer 出现
  // （参照 dsh-client-connection：ctx.inject(["connection","webServer"], …)）。
  if (typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], (svcCtx) => {
      state.transport = registerHttpRoutes(svcCtx, names, handlers) ? 'http-route' : 'none'
    })
    return 'http-route-pending'
  }

  // 兜底：受限上下文没有 ctx.inject 时直接试一次。
  return registerHttpRoutes(ctx, names, handlers) ? 'http-route' : 'none'
}

// --- 余额 -------------------------------------------------------------------

/**
 * 取 API key。**完全照搬官方 provider（dsh-llm-deepseek）的两段式**：
 *
 *   1. 官方凭据服务 `ctx.get('credentials').resolve(ref)`；
 *   2. 取不到时退回「启动环境」：`ctx.get('launchEnvironment')`（launcher 传来的环境快照，
 *      桌面端就是这样把 DEEPSEEK_API_KEY 交给 harness 的），再退回本进程 `process.env`。
 *
 * ⚠️ 这是本项目最后一个、也是最要命的「服务不存在」坑：
 * **桌面端这个 profile 里 `credentials` 服务根本没有注册**（官方 provider 正因如此才写了
 * else 分支 + launchEnvironment 兜底）。我原来只走第一步，于是余额一次都没读成功，
 * 界面上表现为「credentials 服务不可用」+ 胶囊永远停在 pending。
 *
 * 返回值只在内存里用，绝不进入快照/日志。
 */
async function readApiKey(ctx) {
  const ref = API_KEY_REF

  // 第一段：官方凭据服务（web/CLI 部署里有；桌面端没有）
  const credentials = ctx.get('credentials')
  if (credentials && typeof credentials.resolve === 'function') {
    try {
      const resolved = await credentials.resolve(ref)
      if (resolved && resolved.value) {
        return { ok: true, value: resolved.value, source: String(resolved.source || 'credentials') }
      }
    } catch {
      /* 读取失败就继续走下一段，不要在这里就放弃 */
    }
  }

  // 第二段：启动环境快照（launchEnvironment 服务）
  try {
    const snapshot = ctx.get('launchEnvironment')
    if (snapshot && typeof snapshot.get === 'function') {
      const ambient = snapshot.get(ref)
      if (ambient && ambient.value) {
        return { ok: true, value: String(ambient.value), source: String(ambient.source || 'launch') }
      }
    }
  } catch {
    /* 继续走最后一段 */
  }

  // 第三段：本进程环境（launchEnvironment 服务也没注册时的兜底）
  try {
    if (typeof process !== 'undefined' && process && process.env && process.env[ref]) {
      return { ok: true, value: String(process.env[ref]), source: 'process.env' }
    }
  } catch {
    /* 受限上下文没有 process，忽略 */
  }

  return { ok: false, error: `${ref} 未配置：凭据服务与启动环境里都没有找到它（可在 设置 → 模型 里填入）` }
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
      // 标脏即可：真正的落盘由 5 秒一次的刷新节拍和插件卸载时的收尾完成，
      // 不会每次模型调用都写盘。
      state.ledgerDirty = true
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
      // 宿主刚启动、首次读余额还没回来时 at === 0。把它显式标成 pending，
      // 客户端据此显示「…」而不是「✗」——否则每次启动都会闪一下故障态。
      pending: !state.balance.at,
      at: state.balance.at || 0,
      error: state.balance.error ? String(state.balance.error) : null,
      isAvailable: state.balance.isAvailable !== false,
      infos: Array.isArray(state.balance.infos) ? state.balance.infos : [],
    },
    usage: summarize(state.ledger, { topN: 25 }),
    clientDiag: state.clientDiag,
    persistence: {
      enabled: !!(state.storage && state.storage.enabled === true),
      path: (state.storage && state.storage.path) || null,
      reason: (state.storage && state.storage.enabled !== true ? state.storage.reason : null) || null,
      savedAt: state.ledgerSavedAt,
      error: state.ledgerError,
    },
    backfill: state.backfill,
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
  // 每次取快照时顺带把脏账本落盘（不是脏的就直接返回，几乎零开销）。
  // 客户端每 5 秒轮询一次，因此「UI 开着」就等于账本持续落盘。
  snapshot: async () => {
    void flushLedger(false)
    return buildSnapshot()
  },
  // 手动刷新是用户明确要求「现在就写下来」的时刻，用 await 保证返回时已落盘。
  refresh: async () => {
    await refreshBalance(ctx, true)
    await flushLedger(false)
    return buildSnapshot()
  },
  setRefreshMs: async (args) => {
    const next = Number(args && args.ms)
    if (Number.isFinite(next) && next >= 3000 && next <= 3600000) state.refreshMs = next
    return { ok: true, refreshMs: state.refreshMs }
  },
  // 清空累计数据（设置页的「重置累计」按钮），立即落盘。
  resetLedger: async () => {
    resetLedger()
    await flushLedger(true)
    return buildSnapshot()
  },
  // 客户端把渲染/取数的失败原因回传上来，存进快照供排查（见 state.clientDiag 的注释）。
  report: async (args) => {
    const clip = (value, max) => String(value === undefined || value === null ? '' : value).slice(0, max)
    state.clientDiag = {
      at: Date.now(),
      from: clip(args && args.from, 40) || 'unknown',
      message: clip(args && args.message, 600),
      stack: clip(args && args.stack, 1200),
      detail: clip(args && args.detail, 600),
    }
    return { ok: true }
  },
  // 从历史会话日志重建累计消耗。耗时取决于历史日志大小（可能数秒），
  // 所以用 in-flight 标志挡住重复点击，并把结果记进快照供 UI 显示。
  backfill: async () => {
    if (state.backfillInFlight) return buildSnapshot()
    state.backfillInFlight = true
    const startedAt = Date.now()
    try {
      const result = await backfillFromSessions(ctx)
      state.backfill = { ...result, at: Date.now(), elapsedMs: Date.now() - startedAt }
    } catch (error) {
      state.backfill = {
        ok: false,
        error: String((error && error.message) || error),
        at: Date.now(),
        elapsedMs: Date.now() - startedAt,
      }
    } finally {
      state.backfillInFlight = false
    }
    return buildSnapshot()
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
// 与 webServer 同理：常驻平面里 timer 也可能还没就绪，所以用 ctx.inject 等它。
// 账本落盘顺带搭这个节拍（每 5 秒一次、且仅在有改动时），不额外引定时器。
function startRefreshTimer(ownerCtx) {
  const timer = ownerCtx.get('timer')
  if (!timer || typeof timer.interval !== 'function') return
  ownerCtx.effect(() => timer.interval(() => {
    void refreshBalance(ctx, false)
    void flushLedger(false)
  }, state.refreshMs))
}
if (typeof ctx.inject === 'function') ctx.inject(['timer'], startRefreshTimer)
else startRefreshTimer(ctx)

// 插件卸载/更新时收尾落盘，避免丢掉最后几秒的累计。
ctx.effect(() => () => { void flushLedger(true) })

// 启动顺序很重要：**先装载累计数据，再读余额**。
// 反过来的话，首次快照/首次记账会发生在恢复之前，界面会先闪一次「0 元」。
void (async () => {
  await loadPersistedLedger()
  // v0.7.3 自愈：v0.7.0/0.7.1 的自动回填在「一条用量都没读到」时也照样 reset + 盖章
  // （那是把用户累计数据清空的事故版本，见 §5.12 / 附录六第 9 条）。它留下的账本是
  // reset 瞬间新建的：`createdAt` 与 `backfilledAt` 是**同一毫秒**盖的两个章，完全相等 ——
  // 而正常的回填必须逐个 await readSession，绝无可能与建账同一毫秒完成。
  // 这个指纹能让修复版认出来「这章是坏的」：清掉它，让自动回填重跑一次（两阶段守卫，
  // 读不到任何东西就一个字节都不改；且只回放清空之前的事件，不重复计数）。
  if (state.ledger.backfilledAt && state.ledger.backfilledAt === state.ledger.createdAt) {
    state.ledger.backfilledAt = 0
    state.ledgerDirty = true
  }
  // 首次运行（磁盘上还没有回填标记）就**自动**从历史会话日志补齐 ——
  // 用户要的是「历史就在那儿」，不是「自己去找按钮点一下」。
  // 失败只记录原因、不影响实时记账；成功后写入 backfilledAt，以后不再自动跑。
  if (!state.ledger.backfilledAt) {
    const startedAt = Date.now()
    try {
      const result = await backfillFromSessions(ctx)
      state.backfill = { ...result, at: Date.now(), elapsedMs: Date.now() - startedAt, auto: true }
    } catch (error) {
      state.backfill = {
        ok: false,
        error: String((error && error.message) || error),
        at: Date.now(),
        elapsedMs: Date.now() - startedAt,
        auto: true,
      }
    }
  }
  await flushLedger(true)
  await refreshBalance(ctx, true)
})()
