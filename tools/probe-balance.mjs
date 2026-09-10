// ---------------------------------------------------------------------------
// probe-balance.mjs —— 不依赖 DSH 的独立自检脚本。
//
// 用途：排查「插件里余额显示不出来」到底是哪一层的问题。
//   node tools/probe-balance.mjs
//
// 它只从**环境变量** DEEPSEEK_API_KEY 读密钥（不读 .credentials.yaml，
// 符合 README_DSH_GOVERNANCE.md §6「不读取秘密文件」），并且只打印结果与
// 密钥长度/前 6 位，绝不打印完整密钥。
// ---------------------------------------------------------------------------

import { execFile } from 'node:child_process'
import { BALANCE_URL, buildCurlConfig, parseBalance, describeCurlFailure } from '../src/core/deepseek.js'

const key = process.env.DEEPSEEK_API_KEY
if (!key) {
  console.error('未设置环境变量 DEEPSEEK_API_KEY。')
  console.error('临时设置示例（当前 PowerShell 窗口有效）：')
  console.error("  $env:DEEPSEEK_API_KEY='sk-xxxxxxxx'; node tools/probe-balance.mjs")
  process.exit(2)
}
console.log(`密钥：长度 ${key.length}，前缀 ${key.slice(0, 6)}…（其余不打印）`)

const built = buildCurlConfig(key)
if (!built.ok) {
  console.error(`构造请求失败：${built.error}`)
  process.exit(2)
}

const exe = process.platform === 'win32' ? 'curl.exe' : 'curl'
const args = ['--silent', '--show-error', '--max-time', '20', '--config', '-']

execFile(exe, args, { input: built.config, timeout: 30000 }, (error, stdout, stderr) => {
  if (error) {
    console.error(`请求失败：${describeCurlFailure(error.code ?? -1, stderr)}`)
    process.exit(1)
  }
  const parsed = parseBalance(stdout)
  if (!parsed.ok) {
    console.error(`解析失败：${parsed.error}`)
    process.exit(1)
  }
  console.log(`接口：${BALANCE_URL}`)
  console.log(`账户可用：${parsed.isAvailable ? '是' : '否'}`)
  for (const info of parsed.infos) {
    console.log(`  ${info.currency}  总余额 ${info.totalBalance}  =  充值 ${info.toppedUpBalance} + 赠送 ${info.grantedBalance}`)
  }
  if (parsed.infos.length === 0) console.log('  （没有返回任何币种条目）')
})
