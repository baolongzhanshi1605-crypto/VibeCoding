$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runScript = Join-Path $projectRoot "run_check.ps1"
$powershell = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"

& "$projectRoot\install_startup_task.ps1"

$dailyName = "Chaoxing Homework Reminder Daily 20"
$dailyCommand = "`"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -Trigger timer"
schtasks.exe /Create /TN $dailyName /SC DAILY /ST 20:00 /TR $dailyCommand /F | Out-Host

$wakeName = "Chaoxing Homework Reminder Wake"
$wakeCommand = "`"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$runScript`" -Trigger wake"
$wakeQuery = "*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]"
schtasks.exe /Create /TN $wakeName /SC ONEVENT /EC System /MO $wakeQuery /TR $wakeCommand /F | Out-Host

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew
Set-ScheduledTask -TaskName $dailyName -Settings $settings | Out-Null
Set-ScheduledTask -TaskName $wakeName -Settings $settings | Out-Null

Write-Host "Installed requested triggers:"
Write-Host "  - Current-user logon startup shortcut"
Write-Host "  - Daily 20:00 scheduled task: $dailyName"
Write-Host "  - Wake-from-sleep event task: $wakeName"
