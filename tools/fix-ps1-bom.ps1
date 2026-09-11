# ---------------------------------------------------------------------------
# fix-ps1-bom.ps1 —— 给本项目所有 .ps1 补上 UTF-8 BOM。
#
# 为什么需要它：Windows PowerShell 5.1 读 .ps1 时，没有 BOM 就按系统 ANSI
# （简体中文机器上是 GBK）解码。本项目脚本里有大量中文，一旦 BOM 丢失，
# 中文会变成乱码，进而把字符串/注释结构破坏掉，报出一堆莫名其妙的语法错误。
#
# 什么时候会丢：任何不带 BOM 写盘的工具/编辑器（本仓库开发期间被 edit 工具坑过一次）。
# 所以：**改完任何 .ps1，跑一下这个脚本再提交**。
#
# 用法（在项目根执行）：
#   powershell -File tools\fix-ps1-bom.ps1
# ---------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$utf8Bom = New-Object System.Text.UTF8Encoding($true)
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$fixed = 0

Get-ChildItem -Path $ProjectRoot -Recurse -Filter *.ps1 -File | ForEach-Object {
  $bytes = [System.IO.File]::ReadAllBytes($_.FullName)
  $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
  if ($hasBom) {
    Write-Output ("BOM 已有  " + $_.FullName.Substring($ProjectRoot.Length + 1))
    return
  }
  $text = [System.IO.File]::ReadAllText($_.FullName, $utf8NoBom)
  [System.IO.File]::WriteAllText($_.FullName, $text, $utf8Bom)
  Write-Output ("BOM 已补  " + $_.FullName.Substring($ProjectRoot.Length + 1))
  $script:fixed++
}

Write-Output ""
Write-Output ("完成：补了 $fixed 个文件。")
