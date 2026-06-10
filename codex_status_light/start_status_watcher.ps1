$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidPath = Join-Path $projectDir "codex_status_watcher.pid"
$outPath = Join-Path $projectDir "codex_status_watcher.out.log"
$errPath = Join-Path $projectDir "codex_status_watcher.err.log"
$scriptPath = Join-Path $projectDir "codex_status_watcher.py"

if (Test-Path -LiteralPath $pidPath) {
  $oldPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
  if ($oldPid -match '^\d+$' -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
    Write-Output "watcher already running pid=$oldPid"
    exit 0
  }
}

$python = (Get-Command py -ErrorAction SilentlyContinue)
if ($python) {
  $exe = $python.Source
  $arguments = @("-3.11", $scriptPath, "--workspace", "F:\Codex_project", "--port", "COM6", "--interval", "1")
} else {
  $exe = "python"
  $arguments = @($scriptPath, "--workspace", "F:\Codex_project", "--port", "COM6", "--interval", "1")
}

$process = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $projectDir -RedirectStandardOutput $outPath -RedirectStandardError $errPath -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ASCII
Write-Output "watcher started pid=$($process.Id)"
