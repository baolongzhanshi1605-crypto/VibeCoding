$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectDir "runtime"
$pidPath = Join-Path $runtimeDir "codex_link.pid"
$linkPath = Join-Path $projectDir "codex_link.py"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (Test-Path -LiteralPath $pidPath) {
    $oldPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if ($oldPid -match '^\d+$' -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        Write-Output "Codex lifecycle link already running pid=$oldPid"
        exit 0
    }
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    $pythonPath = (& $pythonLauncher.Source -3.11 -c "import sys; print(sys.executable)").Trim()
} else {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}
$pythonwPath = Join-Path (Split-Path -Parent $pythonPath) "pythonw.exe"
$executable = if (Test-Path -LiteralPath $pythonwPath) { $pythonwPath } else { $pythonPath }

$process = Start-Process -FilePath $executable -ArgumentList @($linkPath) -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ASCII
Write-Output "Codex lifecycle link started pid=$($process.Id)"
