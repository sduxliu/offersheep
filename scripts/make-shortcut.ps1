# Create a desktop shortcut for OfferSheep (sheep icon, one-click launcher).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File make-shortcut.ps1
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Add-Type -AssemblyName System.Windows.Forms | Out-Null

$desktop = [Environment]::GetFolderPath('Desktop')
$launcher = Join-Path $repo 'scripts\start-offersheep.ps1'
$icon = Join-Path $repo 'desktop\assets\haru-icon.ico'

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desktop 'OfferSheep.lnk'))
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
$lnk.WorkingDirectory = $repo
if (Test-Path $icon) { $lnk.IconLocation = $icon }
$lnk.Description = 'OfferSheep job search workspace'
$lnk.Save()
Write-Output "Created: $(Join-Path $desktop 'OfferSheep.lnk')"
