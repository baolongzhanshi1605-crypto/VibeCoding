$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectDir "runtime"

foreach ($name in @("codex_link.pid", "desktop_widget.pid")) {
    $pidPath = Join-Path $runtimeDir $name
    if (Test-Path -LiteralPath $pidPath) {
        $pidValue = (Get-Content -LiteralPath $pidPath -Raw).Trim()
        if ($pidValue -match '^\d+$') {
            Stop-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
    }
}

Remove-Item -LiteralPath (Join-Path $runtimeDir "desktop_widget.dismissed") -ErrorAction SilentlyContinue

& (Join-Path $projectDir "stop_dashboard.ps1")
Write-Output "Codex lifecycle link stopped"
