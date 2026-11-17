$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Boot-TaskDefinition.ps1')
$root = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'DormWifiReconnect'
$program = Join-Path $root 'app/DormWifiReconnect.exe'
$runtime = Join-Path $root 'runtime'
$definition = New-DormWifiBootDefinition -ProgramPath $program -RuntimePath $runtime
function Assert-True([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message }; Write-Output ('PASS ' + $Message) }
Assert-True ($definition.Triggers.Count -eq 1 -and $definition.Triggers[0].CimClass.CimClassName -eq 'MSFT_TaskBootTrigger') 'Task triggers on OS startup rather than user login'
Assert-True ($definition.Principal.UserId -in @('SYSTEM','S-1-5-18') -and $definition.Principal.LogonType -eq 'ServiceAccount') 'Task uses SYSTEM without a saved Windows account password'
Assert-True (-not $definition.Settings.RunOnlyIfNetworkAvailable) 'Task may start while the computer has no internet'
Assert-True (-not $definition.Settings.DisallowStartIfOnBatteries -and -not $definition.Settings.StopIfGoingOnBatteries) 'Battery use does not disable recovery'
Assert-True ($definition.Settings.ExecutionTimeLimit -eq 'PT0S') 'Recovery is not killed by a fixed run-time limit'
Assert-True ($definition.Actions[0].Execute -eq $program -and $definition.Actions[0].Arguments -eq ('--run --machine --data-dir "' + $runtime + '"')) 'Task action uses the fixed installed program and protected runtime'
Assert-True ($definition.Settings.MultipleInstances -eq 'IgnoreNew') 'Task scheduler refuses duplicate worker instances'
foreach ($script in @('Boot-TaskDefinition.ps1','Prepare-Boot.ps1','Enable-Boot.ps1','Install-Boot.ps1','build-boot.ps1')) {
    $tokens = $null; $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $script), [ref]$tokens, [ref]$errors) | Out-Null
    Assert-True ($errors.Count -eq 0) ('PowerShell syntax: ' + $script)
}
Write-Output 'No task, startup entry, installed directory or network setting was changed by these checks.'
