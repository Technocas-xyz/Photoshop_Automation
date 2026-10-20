<#
    start_chrome.ps1 — launch YOUR installed Chrome with remote debugging so the
    app can attach to it over CDP (the robust connection mode).

    Why a dedicated profile dir?  Chrome 136+ ignores --remote-debugging-port on
    the DEFAULT profile for security. A separate --user-data-dir is MANDATORY,
    so this script always points Chrome at ./chrome_profile.

    Debugging is bound to 127.0.0.1 ONLY (never 0.0.0.0) so nothing off this
    machine can drive your browser.

    Override the Chrome path with:  $env:CHROME_PATH = "C:\path\to\chrome.exe"
#>

$ErrorActionPreference = "Stop"

$Port = 9222
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProfileDir = Join-Path $ProjectRoot "chrome_profile"
$Url = "https://photoshop.adobe.com"

# --- Locate Chrome ---------------------------------------------------------
function Find-Chrome {
    if ($env:CHROME_PATH -and (Test-Path $env:CHROME_PATH)) {
        return $env:CHROME_PATH
    }
    $candidates = @(
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    return $null
}

$Chrome = Find-Chrome
if (-not $Chrome) {
    Write-Host "Could not find Chrome." -ForegroundColor Red
    Write-Host "Set CHROME_PATH to your chrome.exe, e.g.:"
    Write-Host '  $env:CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"'
    exit 1
}

# --- Port already in use? --------------------------------------------------
$inUse = $false
try {
    $test = Test-NetConnection -ComputerName "127.0.0.1" -Port $Port -WarningAction SilentlyContinue
    $inUse = $test.TcpTestSucceeded
} catch {
    $inUse = $false
}

if ($inUse) {
    # Is it actually a Chrome debug endpoint?
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 -UseBasicParsing
        $info = $resp.Content | ConvertFrom-Json
        Write-Host "Port $Port is already serving a Chrome debug endpoint:" -ForegroundColor Yellow
        Write-Host "  $($info.Browser)"
        Write-Host "Chrome already looks ready — you can run the app or login_once.py."
        exit 0
    } catch {
        Write-Host "Port $Port is in use but is NOT a Chrome debug endpoint." -ForegroundColor Red
        Write-Host "Close whatever is using port $Port, or set PS_CDP_URL to a free port."
        exit 1
    }
}

# --- Launch ----------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

Write-Host "Starting Chrome:"
Write-Host "  exe     : $Chrome"
Write-Host "  profile : $ProfileDir"
Write-Host "  debug   : http://127.0.0.1:$Port (localhost only)"
Write-Host ""

& $Chrome `
    "--remote-debugging-port=$Port" `
    "--remote-debugging-address=127.0.0.1" `
    "--user-data-dir=$ProfileDir" `
    "--start-maximized" `
    $Url

Write-Host "Chrome launched. Log in to Adobe, then run: python login_once.py"
