$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$profileDir = Join-Path $projectRoot "data\edge_profile"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$loginUrl = "https://passport2.chaoxing.com/login"

if (-not (Test-Path -LiteralPath $edgePath)) {
    throw "Microsoft Edge was not found at: $edgePath"
}

New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
Start-Process -FilePath $edgePath -ArgumentList @(
    "--user-data-dir=`"$profileDir`"",
    "--profile-directory=Default",
    $loginUrl
)
Write-Host "Opened dedicated Chaoxing login window."
Write-Host "Log in manually there, then close that Edge window before running checks."
Write-Host "The dedicated profile is stored under: $profileDir"
