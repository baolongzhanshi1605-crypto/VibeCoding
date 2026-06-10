$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Chaoxing Homework Reminder.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "explorer.exe"
$shortcut.Arguments = "`"$projectRoot`""
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Open the Chaoxing homework reminder project folder"
$shortcut.Save()

Write-Host "Created desktop shortcut: $shortcutPath"
