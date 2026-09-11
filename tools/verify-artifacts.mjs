#!/usr/bin/env node
// ---------------------------------------------------------------------------
// verify-artifacts.mjs —— 不启动 DSH 就能做的构建产物验证。
//
// 覆盖三件事：
//   1. dist/cordis-define.json 的两个函数体语法合法，且调用后返回 { apply }；
//   2. dist/package/lib/client.js （手写的 __ModuleLoader__ 工厂包）能加载、
//      factory 能执行、导出的形状符合客户端插件契约；
//   3. dist/package/lib/index.js （ESM Host 插件）能被 import，
//      apply() 在一个「什么都没有」的空 ctx 下也不抛异常（降级路径）。
//
// 第 2、3 条是「常驻平面之前标注为未验证」的那部分——这个脚本就是补上它。
// 它不写任何文件、不联网、不接触 DSH。
//
// 用法：node tools/verify-artifacts.mjs
// ---------------------------------------------------------------------------

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
let failed = 0

/**
 * 把 DSH_HOME 指到一个临时目录再跑测试。
 * 常驻插件会往 <DSH_HOME>/dsh-api-balance/usage-ledger.json 写累计数据，
 * 验证脚本**绝不能碰用户真实的账本**，所以全程隔离在 dist/verify-home 里，跑完删掉。
 */
const REAL_DSH_HOME = process.env.DSH_HOME
const SANDBOX_HOME = join(root, 'dist', 'verify-home')
rmSync(SANDBOX_HOME, { recursive: true, force: true })
process.env.DSH_HOME = SANDBOX_HOME

function ok(label, detail = '') {
  console.log(`  [PASS] ${label}${detail ? ` — ${detail}` : ''}`)
}
function bad(label, detail = '') {
  console.log(`  [FAIL] ${label}${detail ? ` — ${detail}` : ''}`)
  failed += 1
}

console.log('')
console.log('dsh-api-balance · 构建产物验证')
console.log('')

// --- 1. 动态平面载荷 --------------------------------------------------------
console.log('1. dist/cordis-define.json（动态平面载荷）')
try {
  const payload = JSON.parse(readFileSync(join(root, 'dist/cordis-define.json'), 'utf8'))
  for (const half of ['host', 'client']) {
    const code = payload.code?.[half]
    if (typeof code !== 'string') { bad(`${half} 载荷缺失`); continue }
    try {
      // 动态载荷是「返回 Cordis 插件的函数体」，用空的 ctx 就能安全求值。
      const factory = new Function('ctx', 'harness', 'React', 'host', 'styles', code)
      const plugin = factory(
        { get: () => undefined, on: () => {}, effect: () => {} },
        undefined,
        { createElement: () => ({}), useState: () => [null, () => {}], useEffect: () => {} },
        undefined,
        undefined,
      )
      if (plugin && typeof plugin.apply === 'function') ok(`${half} 载荷语法合法且返回 { apply }`, `${code.length} 字符`)
      else bad(`${half} 载荷没有返回 { apply }`)
    } catch (error) {
      bad(`${half} 载荷求值失败`, String(error.message))
    }
  }
} catch (error) {
  bad('读不到 dist/cordis-define.json', String(error.message))
}

// --- 2. 常驻平面 client bundle ---------------------------------------------
console.log('')
console.log('2. dist/package/lib/client.js（常驻平面 client 包）')
try {
  const source = readFileSync(join(root, 'dist/package/lib/client.js'), 'utf8')
  const stubReact = { createElement: () => ({}), useState: () => [null, () => {}], useEffect: () => {} }
  let registration = null
  const fakeWindow = {
    __ModuleLoader__: {
      load(reg) { registration = reg },
    },
  }
  new Function('window', source)(fakeWindow)
  if (!registration) { bad('bundle 没有调用 window.__ModuleLoader__.load') }
  else {
    ok('bundle 注册成功', `id = ${registration.id}`)
    // 关键交叉校验：bundle 的 id 必须等于 package.json 的 name。
    // dsh-client-modules 用包名作为 boot graph 的行 id，并以此匹配 __ModuleLoader__ 注册；
    // 不相等时加载器报「bundle loaded without registering "<id>"」，客户端静默不加载、
    // 界面上什么都看不到（本地曾把 id 写成插件显示名 dsh-api-balance，踩过这个坑）。
    let declaredName = null
    try {
      declaredName = JSON.parse(readFileSync(join(root, 'dist/package/package.json'), 'utf8')).name
    } catch (error) {
      bad('读不到 dist/package/package.json', String(error.message))
    }
    if (declaredName !== null) {
      if (registration.id === declaredName) ok('bundle id 与 package.json name 一致', declaredName)
      else bad('bundle id 与包名不一致', `bundle 注册 "${registration.id}"，但包名是 "${declaredName}"`)
    }
    if (typeof registration.factory !== 'function') bad('registration.factory 不是函数')
    else {
      const exports = registration.factory((name) => (name === 'react' ? stubReact : {}))
      if (exports && typeof exports.apply === 'function') ok('factory 执行成功且导出 { apply }')
      else bad('factory 没有导出 apply', `实际导出：${Object.keys(exports || {}).join(',')}`)
      // 客户端必须声明等 slots 就绪：常驻插件 apply 得比 slots 注册更早，
      // 不等的话 register 会静默落空（界面全空且无报错）。
      const clientInject = exports && exports.inject
      if (Array.isArray(clientInject) && clientInject.includes('slots')) ok('客户端已声明 inject 含 slots', JSON.stringify(clientInject))
      else bad('客户端 inject 缺少 slots', `实际：${JSON.stringify(clientInject)}`)

      // 行为测试：apply 必须**真的**把 <style> 插进 document.head。
      // 客户端没有 styles 服务，官方插件都是自己插 style 元素；早先本项目只在
      // 「styles builtin / styles 服务」里找，常驻平面两条都拿不到 —— CSS 一行都没注入，
      // 界面全裸、胶囊退化成原生按钮，且完全静默。这条断言守住它。
      const created = []
      globalThis.document = {
        head: { appendChild: (element) => { created.push(element) } },
        createElement: (tag) => ({ tag, textContent: '', setAttribute() {}, remove() {} }),
      }
      try {
        const slotsStub = {
          inject: (_key, callback) => { callback(); return () => {} },
          register: () => () => {},
        }
        const ctxStub = {
          get: (name) => (name === 'slots'
            ? slotsStub
            : name === 'timer'
              ? { interval: () => () => {} }
              : undefined),
          on: () => {},
          effect: (fn) => fn(),
          inject: (_names, callback) => { callback(ctxStub) },
        }
        exports.apply(ctxStub)
        if (created.length === 1 && created[0].tag === 'style' && String(created[0].textContent).includes('.dab-pill')) {
          ok('apply() 已注入样式表', `<style> ${String(created[0].textContent).length} 字符`)
        } else {
          bad('apply() 没有注入样式表', `只插入 ${created.length} 个元素（界面会完全失去样式）`)
        }
      } catch (error) {
        bad('客户端 apply() 模拟执行失败', String(error.message))
      } finally {
        delete globalThis.document
      }
    }
  }
} catch (error) {
  bad('client bundle 加载失败', String(error.message))
}

// --- 3. 常驻平面 host 插件 --------------------------------------------------
console.log('')
console.log('3. dist/package/lib/index.js（常驻平面 host 插件）')
try {
  const mod = await import(pathToFileURL(join(root, 'dist/package/lib/index.js')).href)
  if (typeof mod.apply === 'function') ok('ESM 导入成功且导出 apply', `name = ${mod.name}`)
  else bad('没有导出 apply')

  // 宿主必须声明等 webServer 就绪：常驻插件 apply 得比 webServer 注册更早，
  // 不等的话一条路由都挂不上，后端 404 且没有任何报错。
  const hostInject = mod.inject
  if (Array.isArray(hostInject) && hostInject.includes('webServer')) ok('宿主已声明 inject 含 webServer', JSON.stringify(hostInject))
  else bad('宿主 inject 缺少 webServer', `实际：${JSON.stringify(hostInject)}`)

  // 关键：在一个「什么都没有」的空 ctx 下 apply 也不许抛。
  // 注意这个 ctx 故意不带 inject —— 走的是「兜底直接试一次」那条路径。
  try {
    mod.apply({ get: () => undefined, on: () => {}, effect: () => {} })
    ok('空 ctx 下 apply() 未抛异常', '降级路径生效')
  } catch (error) {
    bad('空 ctx 下 apply() 抛异常', String(error.message))
  }
} catch (error) {
  bad('host 插件导入失败', String(error.message))
}

// --- 4. 宿主传输层行为（端到端模拟，不需重启 DSH）---------------------------
// 这一节专门守住附录四那个坑：常驻平面里 apply 时 webServer 可能还没注册，
// 必须走 ctx.inject 等待；如果又退回「拿不到就静默返回」，这里会立刻红。
console.log('')
console.log('4. 宿主传输层（模拟 Cordis 上下文）')
try {
  const mod = await import(pathToFileURL(join(root, 'dist/package/lib/index.js')).href)
  const routes = []
  const registered = []

  const makeCtx = (withWebServer) => {
    const ctx = {
      get: (name) => (name === 'webServer'
        ? { register: (route) => { routes.push(route); return () => {} } }
        : name === 'timer'
          ? { interval: () => () => {} }
          : undefined),
      on: () => {},
      effect: (fn) => fn(),
      // 模拟 Cordis：inject 在服务已就绪时立刻回调
      inject: (names, cb) => { registered.push(...names); cb(ctx) },
    }
    if (!withWebServer) ctx.get = () => undefined
    return ctx
  }

  mod.apply(makeCtx(true))
  if (routes.length >= 3) {
    ok('宿主通过 ctx.inject 挂上路由', `${routes.length} 条：${routes.map((r) => r.path).join(', ')}`)
  } else {
    bad('宿主没有挂上路由', `只挂到 ${routes.length} 条`)
  }
  if (registered.includes('webServer')) ok('宿主确实对 webServer 发起了 inject')
  else bad('宿主没有 inject webServer', JSON.stringify(registered))

  const kindsOk = routes.every((r) => r.kind === 'exact' && r.path.startsWith('/dsh-api-balance/'))
  if (kindsOk && routes.length > 0) ok('路由形状正确', 'kind=exact + /dsh-api-balance/ 前缀')
  else bad('路由形状不对', JSON.stringify(routes.map((r) => ({ kind: r.kind, path: r.path }))))

  // 端到端：常驻客户端用 GET + ?data=<json> 传参，宿主必须真的解出来。
  // 早先客户端 fetch 不带任何参数，宿主 handler 只收到 {} —— 诊断上报的内容全部丢失。
  const fakeRes = () => {
    const box = { body: '' }
    return { res: { writeHead() {}, end(text) { box.body = text } }, box }
  }
  const findRoute = (suffix) => routes.find((r) => r.path.endsWith(suffix))
  const reportRoute = findRoute('/report')
  const snapshotRoute = findRoute('/snapshot')
  if (reportRoute && snapshotRoute) {
    const payload = { from: 'verify-test', message: 'boom', stack: 'stack-line', detail: 'detail-line' }
    const r1 = fakeRes()
    await reportRoute.handler(
      { url: `/dsh-api-balance/report?data=${encodeURIComponent(JSON.stringify(payload))}` },
      r1.res,
    )
    const r2 = fakeRes()
    await snapshotRoute.handler({ url: '/dsh-api-balance/snapshot' }, r2.res)
    const snap = JSON.parse(r2.box.body)
    if (snap.clientDiag && snap.clientDiag.from === 'verify-test' && snap.clientDiag.message === 'boom') {
      ok('GET ?data= 参数已解析并落到快照 clientDiag', `from=${snap.clientDiag.from}`)
    } else {
      bad('参数没有传到 handler', `clientDiag=${JSON.stringify(snap.clientDiag)}`)
    }
    if (snap.balance && typeof snap.balance.pending === 'boolean') ok('balance.pending 标志存在', `pending=${snap.balance.pending}`)
    else bad('balance 缺少 pending 标志（启动瞬间会闪一次故障态）')
  } else {
    bad('找不到 report / snapshot 路由')
  }
} catch (error) {
  bad('宿主传输层模拟失败', String(error.message))
}

// --- 5. 凭据解析链路（端到端）----------------------------------------------
// 守住本项目最后一个、也是最要命的坑：桌面端 profile 里**没有 credentials 服务**，
// 官方 provider（dsh-llm-deepseek）因此写了 else 分支走 launchEnvironment。
// 只实现 credentials 一段的话，余额会一次都读不出来（界面显示「credentials 服务不可用」）。
console.log('')
console.log('5. 凭据解析与余额读取（模拟桌面端：无 credentials 服务）')
try {
  const mod = await import(pathToFileURL(join(root, 'dist/package/lib/index.js')).href)
  const routes = []
  const curlBody = JSON.stringify({
    is_available: true,
    balance_infos: [{ currency: 'CNY', total_balance: '4.04', granted_balance: '0', topped_up_balance: '4.04' }],
  })
  const desktopLikeCtx = {
    get: (name) => {
      if (name === 'webServer') return { register: (route) => { routes.push(route); return () => {} } }
      if (name === 'launchEnvironment') {
        return { get: (n) => (n === 'DEEPSEEK_API_KEY' ? { value: 'sk-verify-test', source: 'launch' } : undefined) }
      }
      if (name === 'subprocess') {
        return {
          resolveExecutable: async () => 'C:\\WINDOWS\\system32\\curl.exe',
          spawn: () => ({
            done: Promise.resolve({ exitCode: 0 }),
            collected: {
              stdout: { readFrom: () => ({ text: curlBody }) },
              stderr: { readFrom: () => ({ text: '' }) },
            },
          }),
        }
      }
      if (name === 'timer') return { interval: () => () => {} }
      return undefined // credentials 故意缺席 —— 桌面端就是这个情况
    },
    on: () => {},
    effect: (fn) => fn(),
    inject: (_names, callback) => { callback(desktopLikeCtx) },
  }
  mod.apply(desktopLikeCtx)

  const box = { body: '' }
  const refreshRoute = routes.find((r) => r.path.endsWith('/refresh'))
  if (!refreshRoute) bad('找不到 refresh 路由')
  else {
    await refreshRoute.handler({ url: '/dsh-api-balance/refresh' }, { writeHead() {}, end(text) { box.body = text } })
    const snap = JSON.parse(box.body)
    if (snap.apiKey && snap.apiKey.configured === true) {
      ok('credentials 缺席时经 launchEnvironment 取到密钥', `source=${snap.apiKey.source}`)
    } else {
      bad('仍然取不到密钥', `${JSON.stringify(snap.apiKey)} / ${snap.balance && snap.balance.error}`)
    }
    const info = snap.balance && snap.balance.infos && snap.balance.infos[0]
    if (snap.balance && snap.balance.ok === true && info && info.totalBalance === 4.04) {
      ok('余额接口调用与解析正确', `${info.currency} ${info.totalBalance}`)
    } else {
      bad('余额解析失败', JSON.stringify(snap.balance))
    }
    if (snap.balance && snap.balance.pending === false) ok('读成功后 pending 已清除')
    else bad('pending 标志未正确清除', `pending=${snap.balance && snap.balance.pending}`)
  }
} catch (error) {
  bad('凭据链路模拟失败', String(error.message))
}

// --- 6. 累计持久化（端到端：模拟「重启一次后累计还在」）--------------------
console.log('')
console.log('6. 累计持久化（记账 → 落盘 → 重新加载）')
try {
  const mod = await import(pathToFileURL(join(root, 'dist/package/lib/index.js')).href)

  const makePluginCtx = () => {
    const routes = []
    const listeners = {}
    const ctx = {
      get: (name) => {
        if (name === 'webServer') return { register: (route) => { routes.push(route); return () => {} } }
        if (name === 'launchEnvironment') {
          return { get: (n) => (n === 'DEEPSEEK_API_KEY' ? { value: 'sk-verify-test', source: 'launch' } : undefined) }
        }
        if (name === 'subprocess') {
          return {
            resolveExecutable: async () => 'C:\\WINDOWS\\system32\\curl.exe',
            spawn: () => ({
              done: Promise.resolve({ exitCode: 0 }),
              collected: {
                stdout: { readFrom: () => ({ text: '{"is_available":true,"balance_infos":[]}' }) },
                stderr: { readFrom: () => ({ text: '' }) },
              },
            }),
          }
        }
        if (name === 'timer') return { interval: () => () => {} }
        return undefined
      },
      on: (name, listener) => { listeners[name] = listener },
      effect: (fn) => fn(),
      inject: (_names, callback) => { callback(ctx) },
    }
    return { ctx, routes, listeners }
  }

  const readSnapshot = async (routes) => {
    const box = { body: '' }
    const route = routes.find((r) => r.path.endsWith('/snapshot'))
    await route.handler({ url: '/dsh-api-balance/snapshot' }, { writeHead() {}, end(text) { box.body = text } })
    return JSON.parse(box.body)
  }

  // 第一次运行：记一笔账
  const first = makePluginCtx()
  mod.apply(first.ctx)
  await new Promise((resolve) => setTimeout(resolve, 20)) // 等 loadPersistedLedger/flush 完成

  const streamListener = first.listeners['llm/stream']
  if (typeof streamListener !== 'function') {
    bad('没有注册 llm/stream 监听器')
  } else {
    const tap = streamListener(
      { provider: 'deepseek-official', model: 'deepseek-flash', messages: [] },
      () => (async function* () {
        yield { type: 'usage', usage: { inputTokens: 1000, outputTokens: 100, cacheReadTokens: 9000 } }
      })(),
    )
    for await (const _chunk of tap) { /* 消费掉，触发 finally 里的记账 */ }
    await new Promise((resolve) => setTimeout(resolve, 20))

    const afterFirst = await readSnapshot(first.routes)
    const ledgerFile = join(SANDBOX_HOME, 'dsh-api-balance', 'usage-ledger.json')
    if (afterFirst.usage.calls === 1 && afterFirst.usage.costTotal > 0) {
      ok('记账生效', `${afterFirst.usage.calls} 次调用 · $${afterFirst.usage.costTotal.toFixed(6)}`)
    } else {
      bad('记账没有生效', JSON.stringify({ calls: afterFirst.usage.calls, cost: afterFirst.usage.costTotal }))
    }
    if (afterFirst.persistence && afterFirst.persistence.enabled === true) {
      ok('持久化已启用', afterFirst.persistence.path)
    } else {
      bad('持久化未启用', JSON.stringify(afterFirst.persistence))
    }

    // 触发一次落盘（走 refresh 路由，与真实节拍一致）
    const refreshRoute = first.routes.find((r) => r.path.endsWith('/refresh'))
    await refreshRoute.handler({ url: '/dsh-api-balance/refresh' }, { writeHead() {}, end() {} })
    await new Promise((resolve) => setTimeout(resolve, 60))
    if (existsSync(ledgerFile)) ok('账本已落盘', ledgerFile.replace(root, '.'))
    else bad('账本文件没有生成', ledgerFile)

    // 第二次运行：模拟重启
    const second = makePluginCtx()
    mod.apply(second.ctx)
    await new Promise((resolve) => setTimeout(resolve, 40))
    const afterSecond = await readSnapshot(second.routes)
    if (afterSecond.usage.restored === true && afterSecond.usage.calls === 1) {
      ok('重启后累计被恢复', `calls=${afterSecond.usage.calls} · 已运行 ${afterSecond.usage.runs} 次`)
    } else {
      bad('重启后累计没有恢复', JSON.stringify({ restored: afterSecond.usage.restored, calls: afterSecond.usage.calls }))
    }
    if (afterSecond.usage.costTotal > 0) ok('累计花费保留', `$${afterSecond.usage.costTotal.toFixed(6)}`)
    else bad('累计花费丢失')

    // 重置累计
    const resetRoute = second.routes.find((r) => r.path.endsWith('/resetLedger'))
    if (!resetRoute) bad('找不到 resetLedger 路由')
    else {
      const box = { body: '' }
      await resetRoute.handler({ url: '/dsh-api-balance/resetLedger' }, { writeHead() {}, end(text) { box.body = text } })
      const afterReset = JSON.parse(box.body)
      if (afterReset.usage.calls === 0 && afterReset.usage.costTotal === 0) ok('重置累计生效')
      else bad('重置累计无效', JSON.stringify({ calls: afterReset.usage.calls }))
    }

    // 坏文件不该让插件失效
    const ledgerMod = await import(pathToFileURL(join(root, 'dist/package/lib/core/ledger.js')).href)
    const scratch = ledgerMod.createLedger()
    const acceptedBadVersion = ledgerMod.importLedger(scratch, { version: 999, calls: 12345 })
    const acceptedGarbage = ledgerMod.importLedger(scratch, null)
    if (acceptedBadVersion === false && acceptedGarbage === false) ok('损坏/未知版本的账本被安全忽略', '不会读出垃圾，也不会抛异常')
    else bad('损坏的账本处理不正确')
  }
} catch (error) {
  bad('持久化端到端模拟失败', String(error.message))
}

// --- 7. 回填历史消耗（守住「上游服务契约读错」这一类缺陷）-------------------
// 附录六第 10 条：回填曾同时踩两个坑 —— id 读 `record.id`（实际在 `record.header.id`）、
// 事件流用 `listEvents`（其记录**没有 `data`**，永远取不到 usage）。
// 这一节把上游的**真实**返回形状照抄进来（含那个「没有 data」的陷阱版本），
// 任何人把 readSession 改回 listEvents，这里立刻红。
//
// ⚠️ 必须留在第 6 节 DSH_HOME 隔离沙箱的**清理之前**：回填会重建账本并落盘，
//    跑在真实 DSH_HOME 上就会把用户真实累计数据覆盖掉（v0.7.1 真实事故）。
console.log('')
console.log('7. 回填历史消耗（模拟 sessionQuery 的真实返回形状）')
try {
  const mod = await import(pathToFileURL(join(root, 'dist/package/lib/index.js')).href)

  // 用「相对当前时间的 10 天前」而不是写死日期：既保证早于「清空那一刻」（不会被
  // skippedRecent 跳过），也不受运行机器时钟影响。
  const PAST = Date.now() - 10 * 24 * 60 * 60 * 1000
  const usageOf = (inputTokens, outputTokens, cacheReadTokens) => ({ inputTokens, outputTokens, cacheReadTokens })

  // 真实形状①：listSessions → [{ header: { id, createdAt }, live, persisted }]
  const sessionRecords = [
    { header: { id: 'session-alpha', createdAt: PAST - 1000, title: 'A' }, live: false, persisted: true },
    { header: { id: 'session-beta', createdAt: PAST - 2000, title: 'B' }, live: true, persisted: true },
  ]
  // 真实形状②：readSession → { session, inheritedEventCount, events }，events 是完整原始事件（含 data）
  const fullEventsOf = (sessionId) => [
    { seq: 0, type: 'user/message', time: PAST, data: { message: { role: 'user' } } },
    {
      seq: 1,
      type: 'assistant/message',
      time: PAST + 10,
      data: {
        turn: 1,
        step: 1,
        purpose: 'chat',
        usage: usageOf(2000, 300, 8000),
        message: { source: { provider: 'deepseek-official', model: 'deepseek-flash' } },
      },
    },
    {
      seq: 2,
      type: 'assistant/message',
      time: PAST + 20,
      data: {
        turn: 1,
        step: 2,
        purpose: 'chat',
        usage: usageOf(1000, 150, 4000),
        message: { source: { provider: 'deepseek-official', model: 'deepseek-v4-pro' } },
      },
    },
  ]
  // 真实形状③（陷阱）：listEvents 只给轻量记录，**没有 data**。
  // 它刻意不抛异常、也不返回空数组 —— 所以「用错 API」不会报错，只会静默 0 命中。
  const lightweightEventsOf = (sessionId) => [
    { sessionId, seq: 0, type: 'user/message', time: PAST, surface: 'current' },
    { sessionId, seq: 1, type: 'assistant/message', time: PAST + 10, surface: 'current' },
    { sessionId, seq: 2, type: 'assistant/message', time: PAST + 20, surface: 'current' },
  ]

  const routes = []
  const ctx = {
    get: (name) => {
      if (name === 'webServer') return { register: (route) => { routes.push(route); return () => {} } }
      if (name === 'timer') return { interval: () => () => {} }
      if (name === 'sessionQuery') {
        return {
          listSessions: async () => sessionRecords,
          readSession: async (id) => ({ session: { id }, inheritedEventCount: 0, events: fullEventsOf(id) }),
          readSurface: async (id) => ({ session: { id }, inheritedEventCount: 0, events: fullEventsOf(id) }),
          listEvents: async (id) => lightweightEventsOf(id),
        }
      }
      return undefined
    },
    on: () => {},
    effect: (fn) => fn(),
    inject: (_names, callback) => { callback(ctx) },
  }
  mod.apply(ctx)
  await new Promise((resolve) => setTimeout(resolve, 20))

  const hit = async (suffix) => {
    const route = routes.find((r) => r.path.endsWith(suffix))
    if (!route) throw new Error(`找不到路由 ${suffix}`)
    const box = { body: '' }
    await route.handler(
      { url: `/dsh-api-balance/${suffix.replace(/^\//, '')}` },
      { writeHead() {}, end(text) { box.body = text } },
    )
    return JSON.parse(box.body)
  }

  const result = await hit('/backfill')
  const bf = result.backfill || {}
  if (bf.ok === true) ok('回填成功', `命中 ${bf.matched} 次调用（扫描 ${bf.sessionsScanned}/${bf.sessionCount} 个会话）`)
  else bad('回填失败', `error=${bf.error} · 诊断=${JSON.stringify({ sessionCount: bf.sessionCount, sessionsWithoutId: bf.sessionsWithoutId, readEventsFailed: bf.readEventsFailed, firstSessionKeys: bf.firstSessionKeys, firstHeaderKeys: bf.firstHeaderKeys, firstEventKeys: bf.firstEventKeys })}`)

  // 核心断言①：id 是从 record.header.id 取到的
  if (bf.sessionsWithoutId === 0) ok('会话 id 从 record.header.id 取出', '不再是「全部缺 id」')
  else bad('仍有会话读不到 id', `sessionsWithoutId=${bf.sessionsWithoutId}（id 在 record.header.id 里）`)

  if (bf.sessionsScanned === sessionRecords.length) ok('每个会话都被读到', `${bf.sessionsScanned} 个`)
  else bad('有会话没被扫描', `${bf.sessionsScanned}/${sessionRecords.length}`)

  // 核心断言②：事件流是从 readSession 拿的完整事件
  if (bf.matched === 4) ok('两条会话 × 各 2 次带用量调用 = 4 次', '事件流确实带 data.usage')
  else bad('命中数与预期不符', `matched=${bf.matched}，预期 4（若为 0 说明事件流又退回了没有 data 的 listEvents）`)

  if (bf.sessionsWithoutId === 0 && bf.matched === 0) {
    bad('事件流 API 用错了', '能拿到 id 但读不到用量 —— listEvents 的记录没有 data，必须用 readSession')
  }

  // 核心断言③：回填结果真的写进了累计账本（而不是只报了个数字）
  const calls = result.usage && typeof result.usage.calls === 'number' ? result.usage.calls : -1
  if (calls === 4) ok('回填结果已进入累计账本', `usage.calls=${calls}`)
  else bad('回填没有正确写进账本', `usage.calls=${calls}，预期 4`)

  const cacheHit = result.usage && result.usage.cacheHitTokens
  // 2 个会话 × (8000 + 4000) = 24000
  if (typeof cacheHit === 'number' && cacheHit === 24000) {
    ok('缓存命中输入被正确分类', `cacheHitTokens=${cacheHit}`)
  } else {
    bad('缓存命中分类不对', `cacheHitTokens=${JSON.stringify(cacheHit)}，预期 24000`)
  }

  // 前提复核：确认「用错 API 会静默失败」这个判断仍然成立。
  // 若哪天 listEvents 开始返回 data，说明上游契约变了，本节与 §5.12 都需要重新对照。
  if (lightweightEventsOf('x').every((e) => e.data === undefined)) {
    ok('前提复核：listEvents 轻量记录确实没有 data', '所以取用量必须走 readSession')
  } else {
    bad('前提变了：listEvents 现在带 data 了', '请重新对照上游契约并更新 §5.12')
  }

  // 自愈守卫：v0.7.0/0.7.1 的事故版本会在「读到 0 条」时也 reset + 盖章，
  // 留下 `backfilledAt === createdAt` 的坏章（同一毫秒盖的两个章 —— 正常回填
  // 必须逐个 await readSession，绝无可能同毫秒完成）。修复版启动时必须认出它、
  // 清掉它、并自动重跑一次回填；否则用户的自动回填被坏章永久挡住。
  const ledgerFile = join(SANDBOX_HOME, 'dsh-api-balance', 'usage-ledger.json')
  const brokenStamp = Date.now() - 5 * 60 * 1000
  const brokenLedger = {
    version: 1,
    createdAt: brokenStamp,
    updatedAt: brokenStamp,
    runs: 2,
    backfilledAt: brokenStamp,
    calls: 3,
    cacheHitTokens: 3000,
    costTotal: 0.009,
  }
  mkdirSync(dirname(ledgerFile), { recursive: true })
  writeFileSync(ledgerFile, JSON.stringify(brokenLedger), 'utf8')

  const healRoutes = []
  const healCtx = {
    get: (name) => {
      if (name === 'webServer') return { register: (route) => { healRoutes.push(route); return () => {} } }
      if (name === 'timer') return { interval: () => () => {} }
      if (name === 'sessionQuery') {
        return {
          listSessions: async () => sessionRecords,
          readSession: async (id) => ({ session: { id }, inheritedEventCount: 0, events: fullEventsOf(id) }),
          readSurface: async (id) => ({ session: { id }, inheritedEventCount: 0, events: fullEventsOf(id) }),
          listEvents: async (id) => lightweightEventsOf(id),
        }
      }
      return undefined
    },
    on: () => {},
    effect: (fn) => fn(),
    inject: (_names, callback) => { callback(healCtx) },
  }
  mod.apply(healCtx)
  await new Promise((resolve) => setTimeout(resolve, 80)) // 等装载 + 自愈 + 自动回填跑完

  const healSnapshotRoute = healRoutes.find((r) => r.path.endsWith('/snapshot'))
  const healBox = { body: '' }
  await healSnapshotRoute.handler({ url: '/dsh-api-balance/snapshot' }, { writeHead() {}, end(text) { healBox.body = text } })
  const healed = JSON.parse(healBox.body)
  const healedBf = healed.backfill || {}
  if (healedBf.auto === true && healedBf.ok === true) {
    ok('坏章被认出并自动重跑回填', `auto=${healedBf.auto} · 命中 ${healedBf.matched} 次`)
  } else {
    bad('坏章没有被自愈', JSON.stringify({ auto: healedBf.auto, ok: healedBf.ok, error: healedBf.error }))
  }
  if (healed.usage && healed.usage.calls === 4) {
    ok('自愈后账本是日志重建的结果', `usage.calls=${healed.usage.calls}（坏章账本的 3 次被正确重建覆盖）`)
  } else {
    bad('自愈后账本不对', `usage.calls=${JSON.stringify(healed.usage && healed.usage.calls)}，预期 4`)
  }
} catch (error) {
  bad('回填端到端模拟失败', String(error.message))
}

// 收尾：还原本机 DSH_HOME，并清掉隔离目录
process.env.DSH_HOME = REAL_DSH_HOME
rmSync(SANDBOX_HOME, { recursive: true, force: true })

// --- 8. 文档同步（用户明确要求：技术文档必须时刻是最新的）-------------------
// 「改了代码忘了写文档」在这里当场变红，不靠记性。
console.log('')
console.log('8. 文档同步')
try {
  const pkgVersion = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version
  const tag = `v${pkgVersion}`
  const technical = readFileSync(join(root, 'docs/TECHNICAL.md'), 'utf8')
  const readme = readFileSync(join(root, 'README.md'), 'utf8')

  if (technical.includes(tag)) ok('docs/TECHNICAL.md 变更记录已包含当前版本', tag)
  else bad('技术文档没记录当前版本', `package.json 是 ${tag}，但变更记录里找不到它 —— 先补文档再提交`)

  if (/^> 版本：\*\*v[\d.]+\*\*/m.test(technical) && technical.includes(`**${tag}**`)) {
    ok('docs/TECHNICAL.md 头部版本号已同步', tag)
  } else {
    bad('技术文档头部版本号没同步', `应为 **${tag}**`)
  }

  // 每个版本号都要能在变更记录表格里找到一行（防止只改头部忘了记录）
  const rows = technical.match(/^\| \d{4}-\d{2}-\d{2} \| v[\d.]+ \|/gm) || []
  if (rows.length >= 5) ok('变更记录条目数合理', `${rows.length} 条`)
  else bad('变更记录条目太少', `${rows.length} 条`)

  if (readme.includes('累计')) ok('README 已说明累计行为')
  else bad('README 没有提到累计（用户实际会读到这份文档）')
} catch (error) {
  bad('文档同步检查失败', String(error.message))
}

console.log('')
if (failed > 0) {
  console.log(`结果：${failed} 项失败。先运行 node tools/build.mjs 重新构建。`)
  process.exit(1)
}
console.log('结果：全部通过。')
console.log('')
