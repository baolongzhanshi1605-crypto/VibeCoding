$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $projectDir "start_dashboard.ps1")
Start-Process "http://127.0.0.1:8787/display"
