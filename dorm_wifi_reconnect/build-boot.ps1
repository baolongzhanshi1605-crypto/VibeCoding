$ErrorActionPreference = 'Stop'
$env:DOTNET_CLI_HOME = Join-Path $PSScriptRoot '.dotnet'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
Push-Location $PSScriptRoot
try {
    dotnet publish DormWifiReconnect.csproj --configuration Release --output ./dist-boot --nologo --ignore-failed-sources
    if ($LASTEXITCODE -ne 0) { throw 'Boot build failed' }
    dotnet ./dist-boot/DormWifiReconnect.dll --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Boot self-tests failed' }
} finally { Pop-Location }
