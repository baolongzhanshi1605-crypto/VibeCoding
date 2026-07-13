$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $projectDir "start_codex_link.ps1"
$startupDir = [Environment]::GetFolderPath("Startup")
$legacyShortcut = Join-Path $startupDir "Codex Quota Manager.lnk"
$shortcutPath = Join-Path $startupDir "Codex Token Monitor Link.lnk"

Remove-Item -LiteralPath $legacyShortcut -ErrorAction SilentlyContinue

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`""
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "Link Codex desktop lifecycle to the local Token monitor"
$shortcut.Save()

Write-Output "Codex lifecycle startup installed: $shortcutPath"
