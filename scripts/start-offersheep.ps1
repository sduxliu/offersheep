# OfferSheep one-click launcher: start the local server if not running, then open the browser.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File start-offersheep.ps1 [-Port 8080]
param(
    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms | Out-Null
$repo = Split-Path -Parent $PSScriptRoot
$url = "http://localhost:$Port"
$health = "$url/api/health"

function Test-Healthy {
    try {
        $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (-not (Test-Healthy)) {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        $candidate = "D:\visual\anaconda\Scripts\uv.exe"
        if (Test-Path $candidate) { $uv = Get-Item $candidate }
    }
    if (-not $uv) {
        [System.Windows.Forms.MessageBox]::Show('uv not found. Please install uv and add it to PATH.', 'OfferSheep launch failed') | Out-Null
        exit 1
    }
    Start-Process -FilePath $uv.Source -ArgumentList @('run', 'oc', 'start', '--port', "$Port") -WorkingDirectory $repo -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 30; $i += 1) {
        Start-Sleep -Seconds 1
        if (Test-Healthy) { $ready = $true; break }
    }
    if (-not $ready) {
        [System.Windows.Forms.MessageBox]::Show("Server did not start within 30s. Open a terminal, cd `"$repo`", then run: uv run oc start", 'OfferSheep launch failed') | Out-Null
        exit 1
    }
}

Start-Process $url
