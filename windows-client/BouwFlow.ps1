param(
  [string]$Company = "BouwFlow",
  [string]$AppUrl = "https://apps.93-119-6-183.sslip.io"
)

$ErrorActionPreference = "Stop"

# BouwFlow Windows client: the business software stays online so updates are automatic.
# Edge app mode gives the customer a clean standalone window without normal browser controls.
$edgeCandidates = @(
  "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)

$edge = $edgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($edge) {
  Start-Process -FilePath $edge -ArgumentList "--app=$AppUrl", "--start-maximized"
  exit 0
}

# Fallback when Edge cannot be found.
Start-Process $AppUrl
