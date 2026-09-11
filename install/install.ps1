<#
.SYNOPSIS
  安装 dsh-api-balance 常驻插件（重启 DSH 后依然生效）。

.DESCRIPTION
  做三件事，全部限定在 DSH 的 home 目录内，不动别处：
    1. 备份 <home>\profiles\web\cordis.patch.yml → 同名 .bak-<时间戳>；
    2. 把 dist\package 复制到 profiles\web\node_modules\dsh-api-balance-local
       与 profiles\node_modules\dsh-api-balance-local（loader 解析根有两处，都放）；
    3. 用带 BEGIN/END 标记的块，把插件行追加进 cordis.patch.yml（可重复执行，幂等）。

  本脚本只做文件复制与文本追加，不修改注册表、不改系统、不联网。
  卸载用 uninstall.ps1；出问题用 uninstall.ps1 回滚备份。

  ⚠️ 实现注意（踩过一次的坑）：拼接多行文本必须用 [string]::Join + [IO.File]::WriteAllText。
  用 "$a" + $array + "$b" 或 Set-Content 时，PowerShell 会把数组元素用**一个空格**连起来，
  换行会静默丢失 —— 结果是整块 YAML 变成一行注释，插件装上了却完全不生效。

.PARAMETER DshHome
  DSH 的 home 目录。默认取环境变量 DSH_HOME；没有则用桌面端默认路径。

.PARAMETER Profile
  profile 名，默认 web。

.PARAMETER DryRun
  只打印将要做什么，不落盘。

.EXAMPLE
  powershell -File install\install.ps1
  powershell -File install\install.ps1 -DshHome 'C:\Users\han\.dsh' -DryRun
#>
[CmdletBinding()]
param(
  [string]$DshHome = $env:DSH_HOME,
  [string]$Profile = 'web',
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PackageSource = Join-Path $ProjectRoot 'dist\package'
$PackageName = 'dsh-api-balance-local'
$MarkerBegin = '# >>> dsh-api-balance BEGIN'
$MarkerEnd = '# <<< dsh-api-balance END'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Say([string]$m, [string]$color = 'Gray') { Write-Host $m -ForegroundColor $color }
function Step([string]$m) { Write-Host "  · $m" }

if (-not $DshHome) {
  $DshHome = Join-Path $env:APPDATA 'dsh-desktop\harness'
  Say "未提供 -DshHome 且没有 DSH_HOME 环境变量，回退到桌面端默认 home。" 'Yellow'
}
$DshHome = [System.IO.Path]::GetFullPath($DshHome)
if (-not (Test-Path -LiteralPath $DshHome)) { throw "DSH home 不存在：$DshHome" }

$ProfileDir = Join-Path $DshHome "profiles\$Profile"
if (-not (Test-Path -LiteralPath $ProfileDir)) { throw "profile 目录不存在：$ProfileDir" }

$PatchPath = Join-Path $ProfileDir 'cordis.patch.yml'
if (-not (Test-Path -LiteralPath $PatchPath)) { throw "找不到组合补丁：$PatchPath" }

if (-not (Test-Path -LiteralPath $PackageSource)) {
  throw "找不到构建产物 $PackageSource。请先在项目根运行：node tools\build.mjs"
}

Say ""
Say "dsh-api-balance · 常驻安装" 'Cyan'
Say "  DSH home : $DshHome"
Say "  profile  : $Profile"
Say "  补丁文件 : $PatchPath"
Say "  包源     : $PackageSource"
Say "  目标     : profiles\$Profile\node_modules\$PackageName , profiles\node_modules\$PackageName"
Say ""

if ($DryRun) { Say 'DryRun：以下操作不会真正执行。' 'Yellow' }

# --- 1. 备份补丁 -------------------------------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = "$PatchPath.bak-$stamp"
if ($DryRun) { Step "会备份 → $backup" } else { Copy-Item -LiteralPath $PatchPath -Destination $backup -Force; Step "已备份 → $backup" }

# --- 2. 复制插件包到两处 node_modules ---------------------------------------
$targets = @(
  (Join-Path $ProfileDir "node_modules\$PackageName"),
  (Join-Path $DshHome "profiles\node_modules\$PackageName")
)
foreach ($dest in $targets) {
  if ($DryRun) { Step "会复制包 → $dest" ; continue }
  $parent = Split-Path -Parent $dest
  if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
  Copy-Item -LiteralPath $PackageSource -Destination $dest -Recurse -Force
  Step "已复制包 → $dest"
}

# --- 3. 幂等写入组合补丁行 ---------------------------------------------------
$text = [System.IO.File]::ReadAllText($PatchPath, $Utf8NoBom)

if ($text.Contains($MarkerBegin)) {
  Step "补丁里已存在 dsh-api-balance 块，跳过写入（幂等）"
} else {
  # 逐行重建：先按 CRLF 或 LF 切分，去掉尾部空行，再补一个空行分隔，最后追加标记块。
  $lines = [System.Collections.Generic.List[string]]::new()
  foreach ($line in ($text -split "`r?`n")) { $lines.Add($line.TrimEnd("`r")) }
  while ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim() -eq '') { $lines.RemoveAt($lines.Count - 1) }

  $lines.Add('')
  $lines.Add("$MarkerBegin (由 install.ps1 写入；删掉本块并重启即可停用)")
  $lines.Add('- insert:')
  $lines.Add('    - id: dsh-api-balance')
  $lines.Add("      name: $PackageName")
  $lines.Add($MarkerEnd)

  $rebuilt = [string]::Join("`r`n", $lines) + "`r`n"

  if ($DryRun) {
    Step '会追加插件行到 cordis.patch.yml：'
    Say ("      " + $MarkerBegin) 'DarkGray'
    Say '      - insert:' 'DarkGray'
    Say '          - id: dsh-api-balance' 'DarkGray'
    Say "            name: $PackageName" 'DarkGray'
  } else {
    [System.IO.File]::WriteAllText($PatchPath, $rebuilt, $Utf8NoBom)
    Step '已追加插件行到 cordis.patch.yml'
  }
}

# --- 4. 回读自检：确认补丁块真的分成了多行 --------------------------------
if (-not $DryRun) {
  $check = [System.IO.File]::ReadAllText($PatchPath, $Utf8NoBom)
  $checkLines = $check -split "`r?`n"
  $hasInsertRow = $false
  foreach ($line in $checkLines) { if ($line.Trim() -eq '- insert:' -or $line.Trim() -eq 'name: ' + $PackageName) { $hasInsertRow = $true } }
  $sane = $check.Contains($MarkerBegin) -and $check.Contains($MarkerEnd) -and ($checkLines | Where-Object { $_.Trim() -eq '- insert:' }).Count -ge 2
  if ($sane) { Step '回读自检：补丁块分行正常、插件行已就位' }
  else {
    Say "回读自检失败：补丁内容不符合预期，已用备份回滚。" 'Red'
    Copy-Item -LiteralPath $backup -Destination $PatchPath -Force
    throw "补丁写入异常，已回滚到 $backup。请把上面输出发给维护者。"
  }
}

Say ""
Say "完成。请重启 DSH（桌面端请完全退出再启动）后验证：" 'Green'
Say "  powershell -File install\verify.ps1"
Say ""
Say "回滚（出任何问题先做这一步）：" 'Yellow'
Say "  powershell -File install\uninstall.ps1"
Say "  备份文件：$backup"
Say ""
