$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectDir "runtime"
$pidPath = Join-Path $runtimeDir "dashboard.pid"
$outPath = Join-Path $runtimeDir "dashboard.out.log"
$errPath = Join-Path $runtimeDir "dashboard.err.log"
$appPath = Join-Path $projectDir "app.py"
$port = 8790

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (Test-Path -LiteralPath $pidPath) {
    $oldPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if ($oldPid -match '^\d+$' -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        Write-Output "dashboard already running pid=$oldPid"
        Write-Output "local: http://127.0.0.1:$port/display"
        exit 0
    }
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
}

$listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    throw "TCP port $port is already in use by process $($listener[0].OwningProcess)"
}

$pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pythonLauncher) {
    $pythonPath = (& $pythonLauncher.Source -3.11 -c "import sys; print(sys.executable)").Trim()
} else {
    $pythonPath = (Get-Command python -ErrorAction Stop).Source
}

$pythonwPath = Join-Path (Split-Path -Parent $pythonPath) "pythonw.exe"
$executable = if (Test-Path -LiteralPath $pythonwPath) { $pythonwPath } else { $pythonPath }
$arguments = @($appPath, "--host", "0.0.0.0", "--port", "$port", "--poll", "1")

$process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $projectDir -RedirectStandardOutput $outPath -RedirectStandardError $errPath -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ASCII

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 1
        if ($health.status) {
            $ready = $true
            break
        }
    } catch {
        if ($process.HasExited) { break }
    }
}

if (-not $ready) {
    $details = if (Test-Path -LiteralPath $errPath) { Get-Content -LiteralPath $errPath -Tail 20 | Out-String } else { "no error log" }
    throw "dashboard did not become ready. $details"
}

$lanAddress = Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
    Sort-Object InterfaceMetric |
    ForEach-Object { $_.IPAddress } |
    Select-Object -First 1

Write-Output "dashboard started pid=$($process.Id)"
Write-Output "local: http://127.0.0.1:$port/display"
if ($lanAddress) {
    Write-Output "iPad: http://${lanAddress}:$port/display"
}
