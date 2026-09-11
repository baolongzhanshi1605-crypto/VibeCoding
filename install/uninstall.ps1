<#
.SYNOPSIS
  停用 / 回滚 dsh-api-balance 常驻插件。

.DESCRIPTION
  默认做最保守的两件事：
    1. 从 cordis.patch.yml 里删掉带 BEGIN/END 标记的 dsh-api-balance 块；
    2. 保留一份改动后的补丁副本 .uninstalled-<时间戳> 以便再次核对。
  加 -RemovePackage 才会同时删掉复制进 node_modules 的插件包。

  这是「DSH 因为插件崩了」时的第一手段：不需要进 DSH，直接跑这个脚本再重启。

.PARAMETER DshHome
  DSH home 目录，默认同 install.ps1。

.PARAMETER Profile
  profile 名，默认 web。

.PARAMETER RemovePackage
  连同 node_modules 下的插件包一起删除。

.PARAMETER DryRun
  只打印将要做什么。

.EXAMPLE
  powershell -File install\uninstall.ps1
  powershell -File install\uninstall.ps1 -RemovePackage
#>
[CmdletBinding()]
param(
  [string]$DshHome = $env:DSH_HOME,
  [string]$Profile = 'web',
  [switch]$RemovePackage,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$PackageName = 'dsh-api-balance-local'
$MarkerBegin = '# >>> dsh-api-balance BEGIN'
$MarkerEnd = '# <<< dsh-api-balance END'

function Say([string]$m, [string]$color = 'Gray') { Write-Host $m -ForegroundColor $color }
function Step([string]$m) { Write-Host "  · $m" }

if (-not $DshHome) { $DshHome = Join-Path $env:APPDATA 'dsh-desktop\harness' }
$DshHome = [System.IO.Path]::GetFullPath($DshHome)
$ProfileDir = Join-Path $DshHome "profiles\$Profile"
$PatchPath = Join-Path $ProfileDir 'cordis.patch.yml'

Say ""
Say "dsh-api-balance · 停用 / 回滚" 'Cyan'
Say "  补丁文件 : $PatchPath"
Say ""

if (-not (Test-Path -LiteralPath $PatchPath)) { throw "找不到补丁文件：$PatchPath" }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$lines = Get-Content -LiteralPath $PatchPath
$kept = New-Object System.Collections.Generic.List[string]
$skipping = $false
$removed = 0
foreach ($line in $lines) {
  if ($line.Trim() -eq $MarkerBegin -or $line.Trim().StartsWith($MarkerBegin)) { $skipping = $true; $removed++; continue }
  if ($skipping) {
    if ($line.Trim() -eq $MarkerEnd -or $line.Trim().StartsWith($MarkerEnd)) { $skipping = $false }
    continue
  }
  $kept.Add($line)
}
if ($skipping) { Say '警告：补丁里的 END 标记缺失，已删到文件末尾。建议改用 .bak 备份还原。' 'Yellow' }

if ($removed -eq 0) {
  Step '补丁里没有 dsh-api-balance 块（可能本来就已停用）'
} elseif ($DryRun) {
  Step "会从补丁里删除 $removed 个标记块"
} else {
  $archive = "$PatchPath.uninstalled-$stamp"
  Copy-Item -LiteralPath $PatchPath -Destination $archive -Force
  # 必须用 [string]::Join + WriteAllText：PowerShell 用字符串拼接数组时按**单空格**连接，
  # 换行会静默丢失（install.ps1 的注释里记了这个坑的完整来龙去脉）。
  $rebuilt = [string]::Join("`r`n", $kept.ToArray()) + "`r`n"
  [System.IO.File]::WriteAllText($PatchPath, $rebuilt, (New-Object System.Text.UTF8Encoding($false)))
  Step "已删除插件块（改动前的补丁留档 → $archive）"
}

if ($RemovePackage) {
  $targets = @(
    (Join-Path $ProfileDir "node_modules\$PackageName"),
    (Join-Path $DshHome "profiles\node_modules\$PackageName")
  )
  foreach ($dest in $targets) {
    if (-not (Test-Path -LiteralPath $dest)) { Step "不存在，跳过：$dest"; continue }
    if ($DryRun) { Step "会删除：$dest" }
    else { Remove-Item -LiteralPath $dest -Recurse -Force; Step "已删除：$dest" }
  }
} else {
  Step '插件包仍保留在 node_modules（加 -RemovePackage 才会删除）'
}

Say ""
Say "完成。请重启 DSH。" 'Green'
Say "若补丁被改坏，可用最近的 .bak-* / .uninstalled-* 备份整份还原：" 'Yellow'
Get-ChildItem -LiteralPath (Split-Path -Parent $PatchPath) -Filter 'cordis.patch.yml.*' -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 5 |
  ForEach-Object { Say ("  " + $_.Name) }
Say ""
