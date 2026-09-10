// @bundle-order: 3
// ---------------------------------------------------------------------------
// deepseek —— 余额接口的构造与解析（纯函数，零依赖）
//
// 官方接口：GET https://api.deepseek.com/user/balance
//   Authorization: Bearer <API key>
// 响应形如：
//   { "is_available": true,
//     "balance_infos": [ { "currency": "CNY", "total_balance": "110.00",
//                          "granted_balance": "10.00", "topped_up_balance": "100.00" } ] }
//
// 安全要点：API key 只出现在 curl 的 --config 标准输入里，
// 绝不出现在命令行参数（进程列表可见）、也不落盘、不进日志。
// ---------------------------------------------------------------------------

export const BALANCE_URL = 'https://api.deepseek.com/user/balance'
export const API_KEY_REF = 'DEEPSEEK_API_KEY'

/**
 * 生成 curl 的 config 内容（通过 stdin 传入，密钥不入 argv）。
 * 只接受安全字符的密钥，出现引号/换行/控制字符时直接拒绝，避免配置注入。
 */
export function buildCurlConfig(apiKey, url = BALANCE_URL) {
  const key = String(apiKey == null ? '' : apiKey).trim()
  if (!key) return { ok: false, error: 'API key 为空' }
  if (/[\s"'\\\r\n]/.test(key)) return { ok: false, error: 'API key 含非法字符，已拒绝构造请求' }
  const lines = [
    `url = "${url}"`,
    `header = "Authorization: Bearer ${key}"`,
    'header = "Accept: application/json"',
    'header = "User-Agent: dsh-api-balance/0.1"',
    '',
  ]
  return { ok: true, config: lines.join('\n') }
}

/** 解析余额响应文本。任何异常都收敛成 { ok:false, error }，不抛。 */
export function parseBalance(text) {
  let raw
  try {
    raw = JSON.parse(String(text || ''))
  } catch (error) {
    return { ok: false, error: `余额响应不是合法 JSON（${truncate(String(text || ''), 200)}）` }
  }
  if (!raw || typeof raw !== 'object') return { ok: false, error: '余额响应结构异常' }
  if (raw.error) {
    const msg = raw.error.message || raw.error.type || '服务端返回错误'
    return { ok: false, error: String(msg) }
  }
  const infos = Array.isArray(raw.balance_infos) ? raw.balance_infos : []
  return {
    ok: true,
    isAvailable: raw.is_available !== false,
    infos: infos.map((info) => ({
      currency: String(info && info.currency ? info.currency : 'CNY'),
      totalBalance: toNumber(info && info.total_balance),
      grantedBalance: toNumber(info && info.granted_balance),
      toppedUpBalance: toNumber(info && info.topped_up_balance),
    })),
  }
}

/** 从 curl 退出码 + stderr 生成可读错误。 */
export function describeCurlFailure(exitCode, stderr) {
  const detail = truncate(String(stderr || '').trim(), 300)
  const table = {
    6: 'DNS 解析失败（检查网络/DNS）',
    7: '无法连接到 api.deepseek.com（检查网络/代理）',
    28: '请求超时',
    35: 'TLS 握手失败',
    60: '证书验证失败',
  }
  const hint = table[exitCode] || `curl 退出码 ${exitCode}`
  return detail ? `${hint}：${detail}` : hint
}

function toNumber(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const n = Number.parseFloat(String(value == null ? '' : value))
  return Number.isFinite(n) ? n : 0
}

function truncate(text, max) {
  return text.length > max ? `${text.slice(0, max)}…` : text
}
