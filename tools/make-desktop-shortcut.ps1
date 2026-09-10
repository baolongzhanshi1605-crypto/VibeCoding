<#
.SYNOPSIS
  在桌面创建 dsh-api-balance 的管理入口快捷方式。

.DESCRIPTION
  快捷方式指向 tools\desktop-admin.ps1（菜单：打开 DSH / 验证 / 安装 / 停用回滚 / 文档）。
  用 [Environment]::GetFolderPath('Desktop') 取桌面路径，因此 OneDrive 重定向过的
  桌面（本机是 C:\Users\han\OneDrive\桌面）也能正确落位。

  只创建/覆盖一个 .lnk，不动桌面上的其它任何东西。

.PARAMETER Name
  快捷方式文件名（不含 .lnk），默认「DSH API 余额与消耗」。

.PARAMETER Desktop
  覆盖桌面路径，默认自动探测。

.EXAMPLE
  pwsh -File tools\make-desktop-shortcut.ps1
  pwsh -File tools\make-desktop-shortcut.ps1 -Name 'DSH 余额'
#>
[CmdletBinding()]
param(
  [string]$Name = 'DSH API 余额与消耗',
  [string]$Desktop
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AdminScript = Join-Path $ProjectRoot 'tools\desktop-admin.ps1'

if (-not (Test-Path -LiteralPath $AdminScript)) { throw "找不到 $AdminScript" }

if (-not $Desktop) { $Desktop = [Environment]::GetFolderPath('Desktop') }
if (-not (Test-Path -LiteralPath $Desktop)) { throw "桌面路径不存在：$Desktop" }

$pwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshExe) { $pwshExe = (Get-Command powershell -ErrorAction Stop).Source }

$lnkPath = Join-Path $Desktop "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnkPath)
$shortcut.TargetPath = $pwshExe
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$AdminScript`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description = 'dsh-api-balance：DSH API 余额与消耗 —— 管理、验证、停用回滚'
$shortcut.IconLocation = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe,0"
$shortcut.Save()

[System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null

Write-Host ""
Write-Host "已创建桌面快捷方式：" -ForegroundColor Green
Write-Host "  $lnkPath"
Write-Host "  目标：$pwshExe"
Write-Host "  参数：-NoProfile -ExecutionPolicy Bypass -File `"$AdminScript`""
Write-Host ""
