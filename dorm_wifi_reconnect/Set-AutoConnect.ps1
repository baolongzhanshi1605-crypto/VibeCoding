param([Parameter(Mandatory)][string]$ProfileName, [string]$InterfaceName = 'WLAN')
$ErrorActionPreference = 'Stop'
$backupDirectory = Join-Path (Join-Path $PSScriptRoot 'runtime') ('wifi-profile-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $backupDirectory -ErrorAction Stop | Out-Null
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetAccessRuleProtection($true, $false)
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($currentSid)
foreach ($sid in @($currentSid, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'), [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))) {
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid, [Security.AccessControl.FileSystemRights]::FullControl, [Security.AccessControl.InheritanceFlags]'ContainerInherit,ObjectInherit', [Security.AccessControl.PropagationFlags]::None, [Security.AccessControl.AccessControlType]::Allow))
}
Set-Acl -LiteralPath $backupDirectory -AclObject $acl
# No key=clear: the backup retains Windows protection for the wireless key.
& netsh.exe wlan export profile "name=$ProfileName" "interface=$InterfaceName" "folder=$backupDirectory"
if ($LASTEXITCODE -ne 0 -or -not (Get-ChildItem -LiteralPath $backupDirectory -Filter '*.xml' -File)) { throw 'Profile backup failed; connection mode was not changed' }
& netsh.exe wlan set profileparameter "name=$ProfileName" "interface=$InterfaceName" connectionmode=auto
if ($LASTEXITCODE -ne 0) { throw 'Automatic connection setting failed; profile backup is retained' }
Write-Output ('Profile auto-connect enabled. Backup retained: ' + $backupDirectory)
