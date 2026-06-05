$ErrorActionPreference = "SilentlyContinue"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8765"

function Test-Dashboard {
    try {
        $res = Invoke-WebRequest -Uri "$Url/api/summary?days=1" -UseBasicParsing -TimeoutSec 2
        return $res.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-Dashboard)) {
    Start-Process -FilePath "python" -ArgumentList "app.py --no-open" -WorkingDirectory $AppDir -WindowStyle Hidden
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Dashboard) { break }
    }
}

Start-Process $Url
