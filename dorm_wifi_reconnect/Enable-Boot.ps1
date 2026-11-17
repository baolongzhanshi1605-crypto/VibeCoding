param([Parameter(Mandatory)][string]$StageDirectory, [switch]$Rollback)
$ErrorActionPreference = 'Stop'
$stagePath = [IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
if ((Split-Path -Parent $stagePath) -ne (Join-Path $PSScriptRoot 'runtime') -or (Split-Path -Leaf $stagePath) -notmatch '^boot-staging-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$') { throw 'Unexpected boot preparation directory' }
$manifest = Get-Content -LiteralPath (Join-Path $stagePath 'manifest.json') -Raw | ConvertFrom-Json
$expectedLegacy = Join-Path $PSScriptRoot 'dist/DormWifiReconnect.exe'
$expectedData = Join-Path $PSScriptRoot 'runtime'
$expectedShortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'DormWifiReconnect.lnk'
if ($manifest.sourceDataDirectory -ne $expectedData -or $manifest.legacyExecutable -ne [IO.Path]::GetFullPath($expectedLegacy) -or $manifest.legacyShortcut -ne $expectedShortcut) { throw 'Preparation does not belong to the current user installation' }
if (-not $Rollback -and $manifest.legacyShortcutHash) {
    if (-not (Test-Path -LiteralPath $expectedShortcut) -or (Get-FileHash -LiteralPath $expectedShortcut).Hash -ne $manifest.legacyShortcutHash) { throw 'Login startup changed after preparation; preserve it and review again' }
}
$backupShortcut = Join-Path $stagePath 'previous-login-startup.lnk'
if ($manifest.legacyShortcutHash -and ((Get-FileHash -LiteralPath $backupShortcut).Hash -ne $manifest.legacyShortcutHash)) { throw 'Verified login startup backup is missing or changed' }
$installerPath = Join-Path $PSScriptRoot 'Install-Boot.ps1'
$powershellPath = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell/v1.0/powershell.exe'
$arguments = @('-NoProfile','-File',('"' + $installerPath + '"'),'-StageDirectory',('"' + $stagePath + '"'))
if ($Rollback) { $arguments += '-Rollback' }
# UAC is required. Do not change execution policy, security controls, or task permissions to bypass it.
$installer = Start-Process -FilePath $powershellPath -ArgumentList $arguments -Verb RunAs -WindowStyle Hidden -Wait -PassThru
if ($installer.ExitCode -ne 0) { throw 'Elevated operation did not complete; previous user startup was preserved' }
if ($Rollback) {
    if ($manifest.legacyShortcutHash) {
        if (Test-Path -LiteralPath $expectedShortcut) {
            if ((Get-FileHash -LiteralPath $expectedShortcut).Hash -ne $manifest.legacyShortcutHash) { throw 'Another login shortcut exists; refusing overwrite' }
        } else { Copy-Item -LiteralPath $backupShortcut -Destination $expectedShortcut }
    }
    Start-Process -FilePath $expectedLegacy -ArgumentList @('--run','--data-dir',('"' + $expectedData + '"')) -WindowStyle Hidden
    Write-Output 'Boot task disabled; previous user login startup restored. Backups and system installation preserved.'
    exit 0
}
$result = Get-Content -LiteralPath (Join-Path $stagePath 'install-result.json') -Raw | ConvertFrom-Json
if ($result.status -ne 'installed' -or $result.identitySid -ne 'S-1-5-18' -or $result.sessionId -ne 0 -or -not $result.credentialsLoaded) { throw 'Boot task verification did not succeed; previous startup remains' }
$stopper = Start-Process -FilePath $expectedLegacy -ArgumentList @('--stop','--data-dir',('"' + $expectedData + '"')) -WindowStyle Hidden -Wait -PassThru
if ($stopper.ExitCode -ne 0) { throw 'System worker is running, but the previous worker stop request failed; login shortcut retained' }
if ($manifest.legacyShortcutHash) {
    if ((Get-FileHash -LiteralPath $expectedShortcut).Hash -ne $manifest.legacyShortcutHash) { throw 'Login shortcut changed during activation; refusing removal' }
    # Only the exact approved shortcut is replaced, and its verified physical backup is retained.
    Remove-Item -LiteralPath $expectedShortcut
}
Write-Output 'Boot recovery enabled and running as SYSTEM in session 0. Windows sign-in is not required for this task.'
Write-Output 'Restart-and-UU validation has not been performed.'
