#!/usr/bin/env node
// ---------------------------------------------------------------------------
// build.mjs —— 本项目唯一的构建步骤，故意做得极小。
//
// 它把「一份源码」合成为两个运行平面需要的产物：
//
//   dist/cordis-define.json   → 动态平面：喂给 cordis_define 的载荷
//                               （code.host / code.client 是纯函数体，不能有 import）
//   dist/package/             → 常驻平面：可安装的本地 npm 插件包
//                               （lib/index.js 是 ESM；lib/client.js 是手写的
//                                 __ModuleLoader__ 工厂包，不需要任何打包器）
//
// 之所以不引入 rollup/esbuild：本项目的 client 端只依赖 `react` 一个外部模块，
// 浏览器里由 loader 提供，所以真正需要做的只是「拼接 + 去掉 import/export」。
// 少一个构建依赖 = 少一个升级 DSH 后炸掉的地方。
//
// 用法：node tools/build.mjs
// ---------------------------------------------------------------------------

import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = join(here, '..')
const dist = join(root, 'dist')

const read = (relPath) => readFileSync(join(root, relPath), 'utf8')
const write = (relPath, text) => {
  const target = join(dist, relPath)
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, text, 'utf8')
  return target
}

/** 内联顺序即依赖顺序：后一个文件可以直接引用前一个的顶层声明。 */
const CORE_INLINE_ORDER = [
  'src/core/pricing.js',
  'src/core/ledger.js',
  'src/core/deepseek.js',
  'src/core/format.js',
]

/** core/format.js 同时被 Client 半复用（展示口径只写一遍）。 */
const CLIENT_CORE = ['src/core/format.js']

/** 去掉顶层 import / export，让纯函数体可以安全地拼进同一个函数作用域。 */
function stripModuleSyntax(source) {
  return source
    .split('\n')
    .filter((line) => !/^\s*import\s.+from\s+['"].+['"];?\s*$/.test(line))
    .map((line) => line.replace(/^export\s+(?=(?:const|let|var|function|class|async)\b)/, ''))
    .join('\n')
}

function banner(title, source) {
  return `// ${'='.repeat(73)}\n// ${title}\n// 由 tools/build.mjs 从 ${source} 生成 —— 请勿手改，改源文件后重新构建。\n// ${'='.repeat(73)}\n`
}

function concatCore(files) {
  return files.map((file) => `${banner(file, file)}\n${stripModuleSyntax(read(file))}`).join('\n')
}

// --- 组装两个平面的函数体 ---------------------------------------------------

const hostBody = `${concatCore(CORE_INLINE_ORDER)}\n${banner('Host 半 · apply(ctx) 主体', 'src/host.body.js')}\n${stripModuleSyntax(read('src/host.body.js'))}`
const clientBody = `${concatCore(CLIENT_CORE)}\n${banner('Client 半 · apply(ctx) 主体', 'src/client.body.js')}\n${stripModuleSyntax(read('src/client.body.js'))}`

/**
 * 动态平面要求 code.host / code.client 是「返回 Cordis 插件的函数体」，
 * 而 host.body.js / client.body.js 是 apply(ctx) 的**内部**。
 * 这里只加最薄的一层壳，逻辑一行都不改，保证与常驻平面同源。
 *
 * 只给「动态平面载荷」用：删掉**整行都是注释**的行（行首可选空白后紧跟两个斜杠）。
 * 安全性：本项目没有任何跨行字符串或模板里出现「行首双斜杠」的情况
 * （CSS 模板字面量里没有双斜杠），行内块注释与字符串里的 https 地址也不符合
 * 「行首双斜杠」，因此原样保留。
 * 常驻平面（dist/package）保留完整注释——那才是给人读、给人改的产物。
 */
function stripStandaloneCommentLines(source) {
  return source
    .split('\n')
    .filter((line) => !/^\s*\/\//.test(line))
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/**
 * 两个平面的存储桥。
 *
 * 共用函数体里**不能 import**，所以「能不能持久化」这件事由包装层决定：
 *   * 动态平面：受限求值器没有模块系统 → 注入 null，函数体自动退化为「仅内存」；
 *   * 常驻平面：注入一个基于 node:fs/promises 的异步存储。
 *
 * 刻意用**异步** fs：项目红线里写着「不在 Host 半引入同步 IO」。
 * 文件很小（几 KB）且每 5 秒最多写一次，异步完全够用，也不会阻塞事件循环。
 */
const DYNAMIC_STORAGE_DECL = '  const __storage = null\n'
const PERSISTENT_STORAGE_DECL = '  const __storage = __makeLedgerStorage()\n'

function wrapForDefine(body, storageDecl) {
  return `return {\n  apply(ctx) {\n${storageDecl}${stripStandaloneCommentLines(body)}\n  },\n}\n`
}

const defineHost = wrapForDefine(hostBody, DYNAMIC_STORAGE_DECL)
const defineClient = wrapForDefine(clientBody, '')

const version = JSON.parse(read('package.json')).version
const PURPOSE = '在 DSH 界面里实时显示 DeepSeek API 余额，并把每一次模型调用的花费按「缓存命中输入 / 未命中输入 / 输出 / 图片」拆开归因。'

// --- 产物 1：动态平面载荷 ---------------------------------------------------

const definePayload = {
  name: 'DSH API 余额与消耗',
  purpose: PURPOSE,
  code: { host: defineHost, client: defineClient },
}

// --- 产物 2：常驻平面插件包 -------------------------------------------------

const persistentIndex = `// 常驻平面 Host 半：ESM Cordis 插件，与动态平面共用同一份函数体。
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import {
  PRICING_DEFAULT, mergePricing, priceOf, costOfUsage, resolvePriceModel, isPeakAt,
} from './core/pricing.js'
import { createLedger, recordCall, summarize, cacheHitRate, dayKey, MAX_CALL_ROWS, exportLedger, importLedger } from './core/ledger.js'
import { BALANCE_URL, API_KEY_REF, buildCurlConfig, parseBalance, describeCurlFailure } from './core/deepseek.js'
import { fmtMoney, fmtTokens, fmtPct, fmtAgo, fmtBalance, fmtCost, DEFAULT_MONEY } from './core/format.js'

export const name = 'dsh-api-balance'

// 声明硬依赖：常驻插件在组合里 apply 得比 webServer 注册更早，
// 不注入的话 ctx.get('webServer') 会拿到 undefined，插件会静默变成「什么都不做」。
export const inject = ['webServer']

/**
 * 账本持久化桥。只有常驻平面能 import node:fs，所以放在包装层，
 * 共用函数体通过注入进来的 __storage 使用它（见 tools/build.mjs 顶部的说明）。
 *
 * 落点：<DSH_HOME>/dsh-api-balance/usage-ledger.json
 * 刻意**不放在插件包目录里**：install.ps1 每次更新都会先删掉旧包目录再复制，
 * 数据放那儿会被更新顺手抹掉。也不碰 DSH 的设置/凭据/会话，只是一个插件私有数据目录。
 */
function __makeLedgerStorage() {
  const home = (typeof process !== 'undefined' && process.env && process.env.DSH_HOME) || ''
  if (!home) return { enabled: false, path: null, reason: 'DSH_HOME 未设置，累计数据只保留在内存里' }
  const path = join(home, 'dsh-api-balance', 'usage-ledger.json')
  return {
    enabled: true,
    path,
    async read() {
      return await readFile(path, 'utf8')
    },
    async write(text) {
      await mkdir(dirname(path), { recursive: true })
      // 先写临时文件再改名：中途断电/被杀不会留下半截 JSON。
      const temp = path + '.tmp'
      await writeFile(temp, text, 'utf8')
      await rename(temp, path)
      return true
    },
  }
}

${banner('Host 半 · apply(ctx) 主体', 'src/host.body.js')}export function apply(ctx) {
${PERSISTENT_STORAGE_DECL}${stripModuleSyntax(read('src/host.body.js'))}
}
`

/**
 * 常驻插件包的 npm 包名。
 * ⚠️ 这个字符串有**两个**必须一致的用处，改一处必须同时改另一处：
 *   1. package.json 的 name（dsh-client-modules 用它作为 boot graph 的行 id）；
 *   2. client bundle 里 __ModuleLoader__.load({ id }) 的 id。
 * 不一致时加载器会报「bundle 加载了但没注册对应 id」而静默不加载客户端 —— 界面上什么都看不到。
 * tools/verify-artifacts.mjs 会交叉校验这两处，防止再次走丢。
 */
const PACKAGE_NAME = 'dsh-api-balance-local'

const persistentClient = `// 常驻平面 Client 半：手写的 __ModuleLoader__ 工厂包，零打包器。
// 与动态平面共用同一份函数体（core/format.js + src/client.body.js）。
// id 必须是 npm 包名（= boot graph 的行 id），不能是插件显示名。
window.__ModuleLoader__.load({
  id: '${PACKAGE_NAME}',
  factory: (require) => {
    var module = { exports: {} }
    var exports = module.exports

    var React = require('react')

${concatCore(CLIENT_CORE).split('\n').map((l) => (l ? `    ${l}` : l)).join('\n')}

${banner('Client 半 · apply(ctx) 主体', 'src/client.body.js').split('\n').map((l) => (l ? `    ${l}` : l)).join('\n')}    function apply(ctx) {
${stripModuleSyntax(read('src/client.body.js')).split('\n').map((l) => (l ? `      ${l}` : l)).join('\n')}
    }

    exports.apply = apply
    // 与官方客户端插件同构（如 dsh-client-ui-jobs 导出 inject = ["sessions","slots"]）：
    // 让客户端运行时等到 slots 就绪再调用 apply，否则注册会静默落空。
    exports.inject = ['slots']
    return module.exports
  },
})
`

const persistentPackageJson = {
  name: PACKAGE_NAME,
  version,
  private: true,
  description: 'DeepSeek API 余额与消耗面板（DSH 常驻本地插件）。',
  type: 'module',
  main: 'lib/index.js',
  exports: {
    '.': './lib/index.js',
    './client': './lib/client.js',
  },
  dsh: { client: { platform: 'web', inject: [] } },
  license: 'MIT',
}

const patchYml = `# 由 dsh-api-balance 的 install.ps1 合并进 profile 的 cordis.patch.yml。
# 停用方法：删掉这个 insert 块并重启 DSH（或用 install/uninstall.ps1）。
- insert:
    - id: dsh-api-balance
      name: dsh-api-balance-local
`

// --- 写盘 -------------------------------------------------------------------

rmSync(dist, { recursive: true, force: true })

write('cordis-define.json', `${JSON.stringify(definePayload, null, 2)}\n`)
write('package/package.json', `${JSON.stringify(persistentPackageJson, null, 2)}\n`)
write('package/cordis.patch.yml', patchYml)
write('package/lib/index.js', persistentIndex)
write('package/lib/client.js', persistentClient)
// 常驻平面：core/ 必须**原样复制**，保留 export —— lib/index.js 是用 ESM 具名导入引用它们的。
// （去 export 只用于「内联进同一个函数作用域」的动态载荷，两者不可混用；
//   这里曾经误用过一次，被 tools/verify-artifacts.mjs 当场抓出来。）
for (const file of CORE_INLINE_ORDER) {
  write(`package/lib/${file.replace('src/', '')}`, read(file))
}

const hash = (text) => createHash('sha256').update(text).digest('hex').slice(0, 16)
write('manifest.json', `${JSON.stringify({
  version,
  builtAt: new Date().toISOString(),
  hostBodyHash: hash(hostBody),
  clientBodyHash: hash(clientBody),
  defineHostHash: hash(defineHost),
  defineClientHash: hash(defineClient),
  hostBytes: Buffer.byteLength(hostBody),
  clientBytes: Buffer.byteLength(clientBody),
  artefacts: ['cordis-define.json', 'package/'],
}, null, 2)}\n`)

console.log(`[build] version ${version}`)
console.log(`[build] host body   ${Buffer.byteLength(hostBody)} bytes  sha256:${hash(hostBody)}`)
console.log(`[build] client body ${Buffer.byteLength(clientBody)} bytes  sha256:${hash(clientBody)}`)
console.log(`[build] wrote ${dist}`)
