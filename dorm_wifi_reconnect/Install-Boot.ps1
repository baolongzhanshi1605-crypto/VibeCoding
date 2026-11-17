param([Parameter(Mandatory)][string]$StageDirectory, [switch]$Rollback)
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator confirmation is required for the system startup task' }
$installRoot = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'DormWifiReconnect'
$appPath = Join-Path $installRoot 'app'
$runtimePath = Join-Path $installRoot 'runtime'
$backupPath = Join-Path $installRoot 'backups'
$programPath = Join-Path $appPath 'DormWifiReconnect.exe'
$taskName = 'DormWifiReconnect-Boot'
$stagePath = [IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
if ((Split-Path -Parent $stagePath) -ne (Join-Path $PSScriptRoot 'runtime') -or (Split-Path -Leaf $stagePath) -notmatch '^boot-staging-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$') { throw 'Staging path is outside the reviewed project runtime' }
function Assert-NoReparse([string]$Path) {
    $itemPath = [IO.Path]::GetFullPath($Path)
    while ($itemPath) {
        if (Test-Path -LiteralPath $itemPath) {
            $item = Get-Item -LiteralPath $itemPath -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse points are not allowed in installation paths' }
        }
        $parent = Split-Path -Parent $itemPath
        if ($parent -eq $itemPath) { break }; $itemPath = $parent
    }
}
function Set-NewDirectoryAcl([string]$Path, [bool]$UsersRead) {
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    $inherit = [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit'
    foreach ($sidText in @('S-1-5-18','S-1-5-32-544')) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sidText), [Security.AccessControl.FileSystemRights]::FullControl, $inherit, [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow)
        $acl.AddAccessRule($rule)
    }
    if ($UsersRead) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'), [Security.AccessControl.FileSystemRights]::ReadAndExecute, $inherit, [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))
    }
    # Only brand-new task-owned directories are passed here; no existing ACLs are taken over.
    Set-Acl -LiteralPath $Path -AclObject $acl
}
function Assert-OwnTask($Task) {
    if ($Task.Actions.Count -ne 1 -or $Task.Actions[0].Execute -ne $programPath -or $Task.Actions[0].Arguments -ne ('--run --machine --data-dir "' + $runtimePath + '"') -or $Task.Principal.UserId -notin @('SYSTEM','S-1-5-18')) { throw 'Task identity or action differs from this installation' }
}
function Set-NewFileAcl([string]$Path, [bool]$UsersRead) {
    $acl = [Security.AccessControl.FileSecurity]::new()
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
    foreach ($sidText in @('S-1-5-18','S-1-5-32-544')) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sidText), [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.AccessControlType]::Allow))
    }
    if ($UsersRead) {
        $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-32-545'), [Security.AccessControl.FileSystemRights]::ReadAndExecute, [Security.AccessControl.AccessControlType]::Allow))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}
Assert-NoReparse $stagePath
Assert-NoReparse $installRoot
$manifestPath = Join-Path $stagePath 'manifest.json'
if ($Rollback) {
    $installedManifestPath = Join-Path $backupPath 'manifest.json'
    $installedManifest = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
    if ($installedManifest.machineCredentialHash -ne (Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).machineCredentialHash) { throw 'Rollback staging identity does not match installed credentials' }
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop; Assert-OwnTask $task
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    $stopper = Start-Process -FilePath $programPath -ArgumentList @('--stop','--machine','--data-dir',('"' + $runtimePath + '"')) -WindowStyle Hidden -Wait -PassThru
    Start-Sleep -Seconds 2
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    @{ status='rolled-back'; taskDisabled=$true; filesAndBackupsPreserved=$true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stagePath 'rollback-result.json') -Encoding UTF8
    exit 0
}
if (Test-Path -LiteralPath $installRoot) { throw 'Installation root already exists; no overwrite is permitted' }
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Boot task already exists; no overwrite is permitted' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.version -ne 1 -or $manifest.sourceDataDirectory -ne (Join-Path $PSScriptRoot 'runtime')) { throw 'Unexpected preparation manifest' }
$payloadNames = @('DormWifiReconnect.exe','DormWifiReconnect.dll','DormWifiReconnect.deps.json','DormWifiReconnect.runtimeconfig.json')
if (@($manifest.payloadHashes.PSObject.Properties).Count -ne $payloadNames.Count) { throw 'Unexpected payload file count' }
foreach ($name in $payloadNames) {
    $source = Join-Path (Join-Path $stagePath 'payload') $name
    Assert-NoReparse $source
    if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $manifest.payloadHashes.$name) { throw 'Prepared program hash changed' }
}
$credentialSource = Join-Path $stagePath 'credentials.machine.dpapi'
Assert-NoReparse $credentialSource
if ((Get-FileHash -LiteralPath $credentialSource -Algorithm SHA256).Hash -ne $manifest.machineCredentialHash) { throw 'Prepared account data changed' }
$taskCreated = $false
try {
    New-Item -ItemType Directory -Path $installRoot -ErrorAction Stop | Out-Null; Set-NewDirectoryAcl $installRoot $true
    foreach ($path in @($appPath,$runtimePath,$backupPath)) {
        New-Item -ItemType Directory -Path $path -ErrorAction Stop | Out-Null
        Set-NewDirectoryAcl $path ($path -eq $appPath)
    }
    foreach ($name in $payloadNames) {
        $destination = Join-Path $appPath $name
        Copy-Item -LiteralPath (Join-Path (Join-Path $stagePath 'payload') $name) -Destination $destination
        Set-NewFileAcl $destination $true
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $manifest.payloadHashes.$name) { throw 'Installed program hash verification failed' }
    }
    Copy-Item -LiteralPath $credentialSource -Destination (Join-Path $runtimePath 'credentials.machine.dpapi')
    Set-NewFileAcl (Join-Path $runtimePath 'credentials.machine.dpapi') $false
    if ((Get-FileHash -LiteralPath (Join-Path $runtimePath 'credentials.machine.dpapi')).Hash -ne $manifest.machineCredentialHash) { throw 'Installed account data hash verification failed' }
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $backupPath 'manifest.json')
    if (Test-Path -LiteralPath (Join-Path $stagePath 'previous-login-startup.lnk')) { Copy-Item -LiteralPath (Join-Path $stagePath 'previous-login-startup.lnk') -Destination (Join-Path $backupPath 'previous-login-startup.lnk') }
    # Validate restrictive credential directory ACL and deployed file hashes before registering anything.
    foreach ($rule in (Get-Acl -LiteralPath $runtimePath).Access) {
        if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Runtime directory permissions are too broad' }
    }
    . (Join-Path $PSScriptRoot 'Boot-TaskDefinition.ps1')
    $definition = New-DormWifiBootDefinition -ProgramPath $programPath -RuntimePath $runtimePath
    Register-ScheduledTask -TaskName $taskName -InputObject $definition -ErrorAction Stop | Out-Null; $taskCreated = $true
    $task = Get-ScheduledTask -TaskName $taskName; Assert-OwnTask $task
    Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath (Join-Path $backupPath 'installed-task.xml') -Encoding UTF8
    Start-ScheduledTask -TaskName $taskName
    $execution = $null
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        $executionPath = Join-Path $runtimePath 'execution.json'
        if (Test-Path -LiteralPath $executionPath) {
            try { $execution = Get-Content -LiteralPath $executionPath -Raw | ConvertFrom-Json } catch { continue }
            if ($execution.identitySid -eq 'S-1-5-18' -and $execution.sessionId -eq 0 -and $execution.credentialsLoaded -and $execution.online) { break }
        }
    }
    if (-not $execution -or $execution.identitySid -ne 'S-1-5-18' -or $execution.sessionId -ne 0 -or -not $execution.credentialsLoaded -or -not $execution.online) { throw 'Session-0 credential loading and successful internet detection were not verified' }
    if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') { throw 'Boot worker exited during validation' }
    @{ status='installed'; taskName=$taskName; program=$programPath; sessionId=$execution.sessionId; identitySid=$execution.identitySid; credentialsLoaded=$execution.credentialsLoaded; online=$execution.online; rebootTested=$false } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stagePath 'install-result.json') -Encoding UTF8
} catch {
    if ($taskCreated) {
        $task = Get-ScheduledTask -TaskName $taskName; Assert-OwnTask $task
        Disable-ScheduledTask -TaskName $taskName | Out-Null
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    }
    @{ status='failed'; newTaskDisabled=$taskCreated; legacyStartupUnchanged=$true; filesAndBackupsPreserved=$true } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stagePath 'install-result.json') -Encoding UTF8
    throw
}
