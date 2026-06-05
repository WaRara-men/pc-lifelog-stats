$ErrorActionPreference = "Stop"

function Test-Adb {
    try {
        adb version | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Adb)) {
    Write-Host "ADB is not installed or not in PATH."
    Write-Host ""
    Write-Host "Install option:"
    Write-Host "  winget install --id Google.PlatformTools -e"
    Write-Host ""
    Write-Host "After installing, restart PowerShell and run this script again."
    exit 1
}

$devices = adb devices
Write-Host $devices

if ($devices -notmatch "`tdevice") {
    Write-Host ""
    Write-Host "No authorized Android device found."
    Write-Host "1. Enable Developer options on Android."
    Write-Host "2. Enable USB debugging."
    Write-Host "3. Connect USB cable."
    Write-Host "4. Tap Allow on the phone."
    exit 1
}

adb forward tcp:5601 tcp:5600 | Out-Null
Write-Host ""
Write-Host "Android ActivityWatch bridge is ready:"
Write-Host "  PC -> http://127.0.0.1:5601"
Write-Host ""
Write-Host "Open PC Lifelog Stats. Android buckets will be included if ActivityWatch is running on the phone."
