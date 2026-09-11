<#
.SYNOPSIS
  验证 dsh-api-balance 常驻插件是否装好、以及运行时的 HTTP 通道是否通。

.DESCRIPTION
  分两段：
    A. 静态检查（不需要 DSH 在跑）：补丁块、两处 node_modules、包内关键文件。
    B. 运行时检查（需要 DSH 在跑）：请求插件自己注册的三个同源 JSON 接口。

  第二段就是常驻平面客户端用的同一组接口，所以它通了 = 界面一定能拿到数据。

.PARAMETER BaseUrl
  DSH Web 的地址。默认取环境变量 DSH_WEB_URL。

.EXAMPLE
  powershell -File install\verify.ps1
  powershell -File install\verify.ps1 -BaseUrl http://127.0.0.1:50944
#>
[CmdletBinding()]
param(
  [string]$DshHome = $env:DSH_HOME,
  [string]$Profile = 'web',
  [string]$BaseUrl = $env:DSH_WEB_URL
)

$ErrorActionPreference = 'Continue'
$PackageName = 'dsh-api-balance-local'
$MarkerBegin = '# >>> dsh-api-balance BEGIN'
$pass = 0; $fail = 0; $warn = 0

function Ok([string]$m)   { Write-Host "  [PASS] $m" -ForegroundColor Green; $script:pass++ }
function Bad([string]$m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red;   $script:fail++ }
function Warn([string]$m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow; $script:warn++ }

if (-not $DshHome) { $DshHome = Join-Path $env:APPDATA 'dsh-desktop\harness' }
$DshHome = [System.IO.Path]::GetFullPath($DshHome)
$ProfileDir = Join-Path $DshHome "profiles\$Profile"
$PatchPath = Join-Path $ProfileDir 'cordis.patch.yml'

Write-Host ""
Write-Host "dsh-api-balance · 验证" -ForegroundColor Cyan
Write-Host "  DSH home : $DshHome"
Write-Host "  profile  : $Profile"
Write-Host ""

Write-Host "A. 静态检查" -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $PatchPath)) { Bad "找不到补丁文件 $PatchPath" }
else {
  $content = Get-Content -LiteralPath $PatchPath -Raw
  if ($content -and $content.Contains($MarkerBegin)) { Ok '组合补丁里存在 dsh-api-balance 插件行' }
  else { Bad '组合补丁里没有 dsh-api-balance 块（还没安装？）' }
}

foreach ($dest in @(
  (Join-Path $ProfileDir "node_modules\$PackageName"),
  (Join-Path $DshHome "profiles\node_modules\$PackageName")
)) {
  if (Test-Path -LiteralPath $dest) { Ok "插件包存在：$dest" }
  else { Bad "插件包缺失：$dest" }
}

$pkgRoot = Join-Path $ProfileDir "node_modules\$PackageName"
foreach ($rel in @('package.json', 'lib\index.js', 'lib\client.js', 'lib\core\pricing.js')) {
  $f = Join-Path $pkgRoot $rel
  if (Test-Path -LiteralPath $f) { Ok "包内文件：$rel" } else { Bad "包内缺少：$rel" }
}

Write-Host ""
Write-Host "B. 运行时检查" -ForegroundColor Cyan

if (-not $BaseUrl) {
  Warn '没有 DSH_WEB_URL 环境变量，跳过运行时检查（可用 -BaseUrl 指定）'
} else {
  Write-Host "  目标：$BaseUrl"
  foreach ($name in @('snapshot', 'refresh', 'setRefreshMs')) {
    $uri = "$($BaseUrl.TrimEnd('/'))/dsh-api-balance/$name"
    try {
      if ($name -eq 'setRefreshMs') { continue }  # 它是 POST 语义，静态探针不调用
      $r = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 25
      if ($r.StatusCode -eq 200) {
        $json = $r.Content | ConvertFrom-Json
        Ok "GET /dsh-api-balance/$name → 200"
        if ($name -eq 'snapshot') {
          Write-Host ("        余额接口 OK : " + $json.balance.ok) -ForegroundColor Gray
          Write-Host ("        密钥已配置  : " + $json.apiKey.configured + " (来源 " + $json.apiKey.source + ")") -ForegroundColor Gray
          Write-Host ("        已记账调用  : " + $json.usage.calls + " 次，累计 ≈ " + ('{0:N6}' -f $json.usage.costTotal) + " USD") -ForegroundColor Gray
          if (-not $json.balance.ok) { Warn ("余额读取失败：" + $json.balance.error) }
        }
      } else { Bad "GET /dsh-api-balance/$name → HTTP $($r.StatusCode)" }
    } catch {
      Bad "GET /dsh-api-balance/$name → $($_.Exception.Message)"
    }
  }
}

Write-Host ""
Write-Host ("结果：$pass 通过 / $fail 失败 / $warn 警告") -ForegroundColor Cyan
Write-Host ""
if ($fail -gt 0) {
  Write-Host "失败项的排查顺序：" -ForegroundColor Yellow
  Write-Host "  1) 还没安装 → powershell -File install\install.ps1"
  Write-Host "  2) 装了没重启 → 完全退出 DSH Desktop 再启动"
  Write-Host "  3) 重启后仍失败 → powershell -File install\uninstall.ps1 回滚，并查 docs\ROLLBACK.md"
  exit 1
}
