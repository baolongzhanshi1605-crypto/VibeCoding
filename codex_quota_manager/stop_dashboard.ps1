$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidPath = Join-Path $projectDir "runtime\dashboard.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output "dashboard is not running"
    exit 0
}

$pidValue = (Get-Content -LiteralPath $pidPath -Raw).Trim()
if ($pidValue -match '^\d+$') {
    $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id ([int]$pidValue)
        $process.WaitForExit(5000)
        Write-Output "dashboard stopped pid=$pidValue"
    }
}

Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
