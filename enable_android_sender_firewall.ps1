$ErrorActionPreference = "Stop"

$RuleName = "PC Lifelog Android Sender 8766"

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Firewall rule already exists: $RuleName"
    exit 0
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8766 `
    -Profile Private `
    -RemoteAddress LocalSubnet | Out-Null

Write-Host "Firewall rule created: $RuleName"
Write-Host "Only Private network / LocalSubnet is allowed."
