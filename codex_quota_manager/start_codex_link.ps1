$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectDir "runtime"
$pidPath = Join-Path $runtimeDir "codex_link.pid"
$linkPath = Join-Path $projectDir "codex_link.py"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (Test-Path -LiteralPath $pidPath) {
    $oldPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if ($oldPid -match '^\d+$') {
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
        if ($existing -and $existing.Name -match '^pythonw?\.exe$' -and
            $existing.CommandLine -match [regex]::Escape($linkPath)) {
            Write-Output "Codex lifecycle link already running pid=$oldPid"
            exit 0
        }
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

# A resident listener must not inherit the launcher's kill-on-close job.
$launchCode = @'
import subprocess, sys
process = subprocess.Popen(
    sys.argv[1:3], cwd=sys.argv[3], close_fds=True,
    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print(process.pid)
'@
$startedPid = & $pythonPath -c $launchCode $executable $linkPath $projectDir
if ($LASTEXITCODE -ne 0 -or "$startedPid".Trim() -notmatch '^\d+$') {
    throw "Could not start an independent Codex lifecycle listener. No listener was registered. Run this script from Windows PowerShell outside the managed host."
}
$startedPid = "$startedPid".Trim()
Set-Content -LiteralPath $pidPath -Value $startedPid -Encoding ASCII
Write-Output "Codex lifecycle link started pid=$startedPid"
