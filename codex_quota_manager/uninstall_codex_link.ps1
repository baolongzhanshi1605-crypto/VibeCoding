$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex Token Monitor Link.lnk"

Remove-Item -LiteralPath $shortcutPath -ErrorAction SilentlyContinue
& (Join-Path $projectDir "stop_codex_link.ps1")
Write-Output "Codex lifecycle startup removed"
