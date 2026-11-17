# Run only after the user approves creating the current-user login shortcut.
$ErrorActionPreference = 'Stop'
$programPath = Join-Path $PSScriptRoot 'dist/DormWifiReconnect.exe'
$runtimePath = Join-Path $PSScriptRoot 'runtime'
if (-not (Test-Path -LiteralPath $programPath -PathType Leaf)) { throw 'Build the program first' }
$installer = Start-Process -FilePath $programPath -ArgumentList @('--install-startup', '--data-dir', ('"' + $runtimePath + '"')) -WindowStyle Hidden -Wait -PassThru
if ($installer.ExitCode -ne 0) { throw 'Startup shortcut was not installed; inspect any existing shortcut before retrying' }
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'DormWifiReconnect.lnk'
if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) { throw 'Startup shortcut verification failed' }
# This is an intentionally visible account-entry window. Saving starts the background worker.
Start-Process -FilePath $programPath -ArgumentList @('--setup', '--data-dir', ('"' + $runtimePath + '"'))
Write-Output ('Created login startup shortcut: ' + $shortcutPath)
