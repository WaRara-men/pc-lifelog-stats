param(
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LocalData = Join-Path $AppDir "local_data"
$ConfigPath = Join-Path $LocalData "import_sources.json"
$Resolved = (Resolve-Path -LiteralPath $Path).Path

New-Item -ItemType Directory -Force -Path $LocalData | Out-Null

$Config = @{
    paths = @($Resolved)
}

$Config | ConvertTo-Json -Depth 4 | Set-Content -Path $ConfigPath -Encoding UTF8

powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $AppDir "import_android_export.ps1") $Resolved

Write-Host ""
Write-Host "Auto-import source registered:"
Write-Host "  $Resolved"
Write-Host ""
Write-Host "When this file changes, PC Lifelog Stats will import it automatically on refresh/startup."
