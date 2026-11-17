function New-DormWifiBootDefinition {
    param([Parameter(Mandatory)][string]$ProgramPath, [Parameter(Mandatory)][string]$RuntimePath)
    if (-not [IO.Path]::IsPathRooted($ProgramPath) -or -not [IO.Path]::IsPathRooted($RuntimePath)) { throw 'Absolute task paths are required' }
    $action = New-ScheduledTaskAction -Execute $ProgramPath -Argument ('--run --machine --data-dir "' + $RuntimePath + '"') -WorkingDirectory (Split-Path -Parent $ProgramPath)
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT10S'
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    # Network availability cannot be a prerequisite: this task is what restores it.
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    New-ScheduledTask -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Restore saved dorm Wi-Fi and portal authentication before Windows user sign-in. No Windows password is stored.'
}
