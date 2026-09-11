<#
.SYNOPSIS
  dsh-api-balance 的桌面管理菜单：一个入口做完全部维护动作。

.DESCRIPTION
  桌面快捷方式指向本脚本。之所以做成菜单而不是单一直达链接，是因为
  「插件把 DSH 搞崩了」时你需要一个不依赖 DSH 的入口去停用和回滚——
  这就是那个入口。

.EXAMPLE
  powershell -File tools\desktop-admin.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Menu {
  Clear-Host
  Write-Host ""
  Write-Host "  DSH API 余额与消耗 · 管理菜单" -ForegroundColor Cyan
  Write-Host "  ─────────────────────────────────────────────" -ForegroundColor DarkGray
  Write-Host "  项目：$ProjectRoot"
  $home_ = if ($env:DSH_HOME) { $env:DSH_HOME } else { Join-Path $env:APPDATA 'dsh-desktop\harness' }
  Write-Host "  DSH home：$home_" -ForegroundColor DarkGray
  Write-Host ""
  Write-Host "   [1] 打开 DSH（看余额与消耗面板）"      -ForegroundColor White
  Write-Host "   [2] 验证：静态检查 + 运行时接口自检"     -ForegroundColor White
  Write-Host "   [3] 安装成常驻插件（重启 DSH 后仍在）"   -ForegroundColor White
  Write-Host "   [4] 停用 / 回滚常驻插件  ← 出问题时用这个" -ForegroundColor Yellow
  Write-Host "   [5] 只看不改：DryRun 演练安装/卸载"      -ForegroundColor White
  Write-Host "   [6] 打开技术文档"                       -ForegroundColor White
  Write-Host "   [7] 打开回滚与防崩方案"                 -ForegroundColor White
  Write-Host "   [8] 打开项目文件夹"                     -ForegroundColor White
  Write-Host "   [9] 备份推送到 GitHub（需代理在线）"      -ForegroundColor White
  Write-Host "   [0] 退出"                               -ForegroundColor DarkGray
  Write-Host ""
}

function Open-Dsh {
  $exe = 'F:\DSH_Desktop\DSH Desktop\DSH Desktop.exe'
  if (Test-Path -LiteralPath $exe) { Start-Process -FilePath $exe; return }
  if ($env:DSH_WEB_URL) { Start-Process $env:DSH_WEB_URL; return }
  Write-Host "  找不到 DSH Desktop.exe，也没有 DSH_WEB_URL。请手动打开 DSH。" -ForegroundColor Yellow
  Start-Sleep -Seconds 3
}

function Run-Script([string]$relative, [string[]]$extra = @()) {
  $script = Split-Path -Parent $PSScriptRoot | Join-Path -ChildPath $relative
  if (-not (Test-Path -LiteralPath $script)) { Write-Host "  找不到 $script" -ForegroundColor Red; Start-Sleep -Seconds 3; return }
  # 直接在本进程里跑子脚本：不要写 pwsh（本机可能只有 Windows PowerShell 5.1，
  # 写 pwsh 会直接 CommandNotFoundException）。
  & $script @extra
  Write-Host ""
  Read-Host "  按回车返回菜单" | Out-Null
}

while ($true) {
  Menu
  $choice = Read-Host "  请选择"
  switch ($choice.Trim()) {
    '1' { Open-Dsh }
    '2' { Run-Script 'install\verify.ps1' }
    '3' { Run-Script 'install\install.ps1' }
    '4' { Run-Script 'install\uninstall.ps1' }
    '5' {
      Write-Host ""
      Write-Host "  DryRun 演练（不落盘）：" -ForegroundColor Cyan
      Run-Script 'install\install.ps1' @('-DryRun')
    }
    '6' { Start-Process (Join-Path $ProjectRoot 'docs\TECHNICAL.md') }
    '7' { Start-Process (Join-Path $ProjectRoot 'docs\ROLLBACK.md') }
    '8' { Start-Process explorer.exe $ProjectRoot }
    '9' { Run-Script 'tools\push-backup.ps1' }
    '0' { return }
    default { }
  }
}
