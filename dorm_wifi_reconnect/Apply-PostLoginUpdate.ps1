param([Parameter(Mandatory)][string]$SourceDirectory, [Parameter(Mandatory)][string]$ExpectedHashesPath)
$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot 'dist'
$runtime = Join-Path $PSScriptRoot 'runtime'
$source = [IO.Path]::GetFullPath($SourceDirectory).TrimEnd('\')
$program = Join-Path $destination 'DormWifiReconnect.exe'
if (-not $source.StartsWith(([IO.Path]::GetFullPath($runtime).TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $source) -ne 'dist') { throw 'Update source must be a reviewed publication build inside this project runtime' }
$names = @('DormWifiReconnect.exe','DormWifiReconnect.dll','DormWifiReconnect.deps.json','DormWifiReconnect.runtimeconfig.json','DormWifiReconnect.pdb')
$expected = Get-Content -LiteralPath $ExpectedHashesPath -Raw | ConvertFrom-Json
foreach ($name in $names) {
    if (-not $expected.current.$name -or -not $expected.source.$name -or (Get-FileHash -LiteralPath (Join-Path $destination $name)).Hash -ne $expected.current.$name -or (Get-FileHash -LiteralPath (Join-Path $source $name)).Hash -ne $expected.source.$name) { throw 'Reviewed executable, DLL, symbols or runtime metadata changed; nothing was stopped or replaced' }
}
foreach ($path in @($destination,$source,$program)) { if (((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Unexpected linked update path' } }
foreach ($name in $names) { if (-not (Test-Path -LiteralPath (Join-Path $source $name) -PathType Leaf)) { throw 'Update payload is incomplete' } }
$backup = Join-Path $runtime ('app-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $backup -ErrorAction Stop | Out-Null
foreach ($name in $names) {
    $path = Join-Path $destination $name
    if (Test-Path -LiteralPath $path) {
        Copy-Item -LiteralPath $path -Destination (Join-Path $backup $name)
        if ((Get-FileHash -LiteralPath $path).Hash -ne (Get-FileHash -LiteralPath (Join-Path $backup $name)).Hash) { throw 'Backup hash verification failed' }
    }
}
function Stop-OwnWorker {
    $stop = Start-Process -FilePath $program -ArgumentList @('--stop','--data-dir',('"' + $runtime + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($stop.ExitCode -ne 0) { throw 'Worker stop request failed' }
    for ($i = 0; $i -lt 30; $i++) {
        $workers = Get-CimInstance Win32_Process -Filter "Name='DormWifiReconnect.exe'" | Where-Object { $_.ExecutablePath -eq $program -and $_.CommandLine -like '*--run*' -and $_.CommandLine.Contains($runtime) }
        if (-not $workers) { return }
        Start-Sleep -Seconds 1
    }
    throw 'Worker did not stop; no forced termination was used'
}
Stop-OwnWorker
try {
    foreach ($name in $names) {
        Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $destination $name) -Force
        if ((Get-FileHash -LiteralPath (Join-Path $source $name)).Hash -ne (Get-FileHash -LiteralPath (Join-Path $destination $name)).Hash) { throw 'Installed file hash mismatch' }
    }
    $startedAt = Get-Date
    $worker = Start-Process -FilePath $program -ArgumentList @('--run','--data-dir',('"' + $runtime + '"')) -WindowStyle Hidden -PassThru
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if ($worker.HasExited) { throw 'Updated worker exited' }
        $statusPath = Join-Path $runtime 'status.json'
        if (Test-Path -LiteralPath $statusPath) {
            $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
            if ([DateTimeOffset]::Parse($status.updatedAt).LocalDateTime -ge $startedAt -and $status.processId -eq $worker.Id) {
                Write-Output ('Updated post-login worker verified. State: ' + $status.state)
                Write-Output ('Verified previous version retained at: ' + $backup)
                exit 0
            }
        }
    }
    throw 'Updated worker did not publish a fresh status snapshot'
} catch {
    $updateFailure = $_
    $running = Get-CimInstance Win32_Process -Filter "Name='DormWifiReconnect.exe'" | Where-Object { $_.ExecutablePath -eq $program -and $_.CommandLine -like '*--run*' -and $_.CommandLine.Contains($runtime) }
    if ($running) { Stop-OwnWorker }
    foreach ($name in $names) {
        $old = Join-Path $backup $name
        if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination (Join-Path $destination $name) -Force }
    }
    Start-Process -FilePath $program -ArgumentList @('--run','--data-dir',('"' + $runtime + '"')) -WindowStyle Hidden
    throw $updateFailure
}
