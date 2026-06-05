$ErrorActionPreference = "Stop"

$Repo = "WaRara-men/pc-lifelog-stats"
$Description = "Local ActivityWatch dashboard for PC and Android lifelog stats"

gh auth status | Out-Null

if (-not (git remote get-url origin 2>$null)) {
    gh repo create $Repo --public --source . --remote origin --description $Description
}

git push -u origin main

Write-Host "Published: https://github.com/$Repo"
