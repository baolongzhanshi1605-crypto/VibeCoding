$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidPath = Join-Path $projectDir "codex_status_watcher.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
  Write-Output "watcher pid file not found"
  exit 0
}

$pidValue = (Get-Content -LiteralPath $pidPath -Raw).Trim()
if ($pidValue -match '^\d+$') {
  $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
  if ($process) {
    Stop-Process -Id ([int]$pidValue)
    Write-Output "watcher stopped pid=$pidValue"
  } else {
    Write-Output "watcher process already stopped pid=$pidValue"
  }
}

Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
