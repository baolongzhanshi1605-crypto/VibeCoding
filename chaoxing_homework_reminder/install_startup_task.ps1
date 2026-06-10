$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runScript = Join-Path $projectRoot "run_check.ps1"
$startup = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startup "Chaoxing Homework Reminder Startup.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "powershell.exe"
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -Trigger login"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Run local Chaoxing homework reminder when this user logs in"
$shortcut.Save()

Write-Host "Installed current-user startup shortcut: $shortcutPath"
