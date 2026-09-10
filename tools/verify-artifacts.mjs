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

import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
let failed = 0

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

  // 关键：在一个「什么都没有」的 ctx 下 apply 也不许抛。
  // 这直接验证了「不声明硬依赖、拿不到服务就降级」这条设计承诺。
  try {
    mod.apply({ get: () => undefined, on: () => {}, effect: () => {} })
    ok('空 ctx 下 apply() 未抛异常', '降级路径生效')
  } catch (error) {
    bad('空 ctx 下 apply() 抛异常', String(error.message))
  }
} catch (error) {
  bad('host 插件导入失败', String(error.message))
}

console.log('')
if (failed > 0) {
  console.log(`结果：${failed} 项失败。先运行 node tools/build.mjs 重新构建。`)
  process.exit(1)
}
console.log('结果：全部通过。')
console.log('')
