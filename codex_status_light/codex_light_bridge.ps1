param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("idle", "working", "waiting", "done")]
  [string]$State,

  [string]$Port = "COM6",
  [int]$Baud = 115200
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logPath = Join-Path $projectDir "codex_light_bridge.log"
$statePath = Join-Path $projectDir "codex_light_state.txt"

function Write-BridgeLog {
  param([string]$Message)
  $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
  Add-Content -LiteralPath $logPath -Value "$stamp $Message" -Encoding UTF8
}

try {
  $lastState = $null
  if (Test-Path -LiteralPath $statePath) {
    $lastState = (Get-Content -LiteralPath $statePath -Raw -ErrorAction SilentlyContinue).Trim()
  }

  if ($lastState -eq $State) {
    Write-BridgeLog "skip unchanged state=$State"
    exit 0
  }

  $serial = [System.IO.Ports.SerialPort]::new($Port, $Baud, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
  $serial.ReadTimeout = 500
  $serial.WriteTimeout = 500
  $serial.DtrEnable = $false
  $serial.RtsEnable = $false
  $serial.Open()
  Start-Sleep -Milliseconds 80
  $serial.WriteLine($State)
  Start-Sleep -Milliseconds 80
  $serial.Close()
  $serial.Dispose()

  Set-Content -LiteralPath $statePath -Value $State -Encoding ASCII
  Write-BridgeLog "sent state=$State port=$Port"
  exit 0
} catch {
  Write-BridgeLog "error state=$State port=$Port message=$($_.Exception.Message)"
  exit 0
}
