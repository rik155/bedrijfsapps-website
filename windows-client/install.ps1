param(
  [string]$Company = "BouwFlow",
  [string]$Slug = "demo",
  [string]$AppUrl = "https://apps.93-119-6-183.sslip.io"
)

$ErrorActionPreference = "Stop"
$installDir = Join-Path $env:LOCALAPPDATA "BouwFlow"
$launcher = Join-Path $installDir "BouwFlow.ps1"
$config = Join-Path $installDir "config.json"
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"

New-Item -ItemType Directory -Force -Path $installDir | Out-Null

$launcherContent = @'
$ErrorActionPreference = "Stop"
$configPath = Join-Path $PSScriptRoot "config.json"
$config = Get-Content $configPath -Raw | ConvertFrom-Json
$edgeCandidates = @(
  "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) {
  Start-Process -FilePath $edge -ArgumentList "--app=$($config.appUrl)", "--start-maximized"
} else {
  Start-Process $config.appUrl
}
'@
Set-Content -Path $launcher -Value $launcherContent -Encoding UTF8

@{
  company = $Company
  slug = $Slug
  appUrl = $AppUrl
} | ConvertTo-Json | Set-Content -Path $config -Encoding UTF8

$ws = New-Object -ComObject WScript.Shell
foreach ($shortcutPath in @((Join-Path $desktop "BouwFlow.lnk"),(Join-Path $startMenu "BouwFlow.lnk"))) {
  $shortcut = $ws.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = "powershell.exe"
  $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
  $shortcut.WorkingDirectory = $installDir
  $shortcut.Description = "BouwFlow - $Company"
  $shortcut.Save()
}

Add-Type -AssemblyName PresentationFramework
[System.Windows.MessageBox]::Show("BouwFlow is geinstalleerd voor $Company. Je vindt BouwFlow op je bureaublad en in het Startmenu.", "BouwFlow", "OK", "Information") | Out-Null
Start-Process "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
