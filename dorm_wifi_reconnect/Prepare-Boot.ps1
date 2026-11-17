$ErrorActionPreference = 'Stop'
$programPath = Join-Path $PSScriptRoot 'dist-boot/DormWifiReconnect.exe'
$runtimePath = Join-Path $PSScriptRoot 'runtime'
$stagePath = Join-Path $runtimePath ('boot-staging-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
if (-not (Test-Path -LiteralPath $programPath -PathType Leaf)) { throw 'Run build-boot.ps1 first' }
$prepare = Start-Process -FilePath $programPath -ArgumentList @('--prepare-boot', ('"' + $stagePath + '"'), '--data-dir', ('"' + $runtimePath + '"')) -WindowStyle Hidden -Wait -PassThru
if ($prepare.ExitCode -ne 0) { throw 'Boot preparation failed; existing installation and credentials were not replaced' }
if (-not (Test-Path -LiteralPath (Join-Path $stagePath 'manifest.json'))) { throw 'Boot manifest was not produced' }
Write-Output $stagePath
