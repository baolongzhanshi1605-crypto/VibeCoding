$ErrorActionPreference = "Stop"

$ruleName = "Codex Quota Manager (TCP 8790)"
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8790 -Profile Private | Out-Null
    Write-Output "private-network firewall rule added for TCP 8790"
} else {
    Write-Output "firewall rule already exists"
}
