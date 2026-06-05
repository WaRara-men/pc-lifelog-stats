$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ShortcutDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$ShortcutPath = Join-Path $ShortcutDir "PC Lifelog Stats.lnk"
$LauncherPath = Join-Path $AppDir "open_dashboard.ps1"

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$LauncherPath`""
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,102"
$Shortcut.Description = "ActivityWatchのPC/Androidライフログ統計を開く"
$Shortcut.Save()

Write-Host "Start Menu shortcut created: $ShortcutPath"
