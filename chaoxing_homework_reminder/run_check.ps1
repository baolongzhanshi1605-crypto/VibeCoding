param(
    [ValidateSet("login", "unlock", "timer", "manual")]
    [string]$Trigger = "manual"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
python -m cx_reminder.cli --config .\config.json --trigger $Trigger
