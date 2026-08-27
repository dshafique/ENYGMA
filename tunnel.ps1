#Requires -Version 5.1
<#
    Put ENYGMA on https://enygma.arkhm.io through a Cloudflare tunnel.

    Runs on: your machine, in PowerShell.   .\tunnel.cmd

    A tunnel makes an outbound connection to Cloudflare, so nothing is exposed on
    your router and no port is forwarded. Your machine has to be on for the URL to
    answer; that is the trade against putting it on the Spark.

    Every step here is also a command you can run by hand. Nothing is hidden.
#>
param(
    [string]$Hostname = 'enygma.arkhm.io',
    [string]$TunnelName = 'enygma',
    [int]$Port = 4073
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Say($t) { Write-Host "-> $t" -ForegroundColor Cyan }
function Warn($t) { Write-Host "   $t" -ForegroundColor Yellow }
function Fail($t) { Write-Host ''; Write-Host $t -ForegroundColor Red; exit 1 }

# --- 1. cloudflared -------------------------------------------------------
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Fail @"
cloudflared is not installed. Install it, then open a NEW PowerShell and run
this again so the PATH is picked up:

    winget install --id Cloudflare.cloudflared
"@
}
Say "cloudflared found: $((cloudflared --version) -join ' ')"

$cfDir = Join-Path $HOME '.cloudflared'

# --- 2. log in ------------------------------------------------------------
# This opens your browser. You are already signed in, so it is one click:
# pick arkhm.io and authorise. It writes cert.pem here and nothing else.
if (-not (Test-Path (Join-Path $cfDir 'cert.pem'))) {
    Say 'opening your browser to authorise the arkhm.io zone'
    Warn 'Pick arkhm.io in the page that opens, then come back here.'
    cloudflared tunnel login
    if (-not (Test-Path (Join-Path $cfDir 'cert.pem'))) { Fail 'Login did not complete.' }
} else {
    Say 'already authorised (cert.pem present)'
}

# --- 3. the tunnel --------------------------------------------------------
$existing = (cloudflared tunnel list 2>$null) -join "`n"
if ($existing -match [regex]::Escape($TunnelName)) {
    Say "tunnel '$TunnelName' already exists"
} else {
    Say "creating tunnel '$TunnelName'"
    cloudflared tunnel create $TunnelName
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the tunnel.' }
}

# The credentials file is named for the tunnel UUID.
$credentials = Get-ChildItem -Path $cfDir -Filter '*.json' -ErrorAction SilentlyContinue |
               Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $credentials) { Fail "No credentials file in $cfDir. Was the tunnel created?" }
Say "credentials: $($credentials.Name)"

# --- 4. config ------------------------------------------------------------
# Two ingress rules: the hostname, then a catch-all. cloudflared refuses to start
# without a catch-all, which is a good rule and a common first mistake.
$configPath = Join-Path $cfDir 'config.yml'
$config = @(
    "tunnel: $TunnelName",
    "credentials-file: $($credentials.FullName)",
    '',
    'ingress:',
    "  - hostname: $Hostname",
    "    service: http://localhost:$Port",
    '  - service: http_status:404'
)
if (Test-Path $configPath) {
    Copy-Item $configPath "$configPath.backup" -Force
    Warn "existing config.yml backed up to config.yml.backup"
}
[System.IO.File]::WriteAllLines($configPath, $config, (New-Object System.Text.UTF8Encoding($false)))
Say "wrote $configPath"

# --- 5. DNS ---------------------------------------------------------------
# This creates the CNAME in Cloudflare for you. Safe to re-run.
Say "pointing $Hostname at the tunnel"
cloudflared tunnel route dns $TunnelName $Hostname
if ($LASTEXITCODE -ne 0) {
    Warn 'The DNS route failed. If it says the record already exists, that is fine.'
}

# --- 6. the app's origin --------------------------------------------------
# A passkey is bound to one origin. The app has to know it is being served from
# https://enygma.arkhm.io, or the browser and the server will disagree and the
# unlock will refuse with a message that does not explain itself.
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envPath)) { Fail 'No .env here. Run .\quickstart.cmd first.' }
Copy-Item $envPath "$envPath.backup" -Force

$wanted = @{
    'ENYGMA_RP_ID'            = $Hostname
    'ENYGMA_ORIGIN'           = "https://$Hostname"
    'ENYGMA_INSECURE_COOKIES' = '0'
}
$lines = [System.IO.File]::ReadAllLines($envPath)
$out = @()
foreach ($line in $lines) {
    $split = $line.IndexOf('=')
    if ($split -gt 0 -and $wanted.ContainsKey($line.Substring(0, $split).Trim())) { continue }
    $out += $line
}
foreach ($key in $wanted.Keys) { $out += "$key=$($wanted[$key])" }
[System.IO.File]::WriteAllLines($envPath, $out, (New-Object System.Text.UTF8Encoding($false)))
Say 'pointed .env at the public origin (.env.backup keeps the local one)'

Write-Host ''
Write-Host 'Ready. Two windows:' -ForegroundColor Green
Write-Host ''
Write-Host '  1)  .\run.ps1' -ForegroundColor White
Write-Host "  2)  cloudflared tunnel run $TunnelName" -ForegroundColor White
Write-Host ''
Write-Host "Then https://$Hostname" -ForegroundColor Green
Write-Host ''
Warn 'Your passkey was enrolled on localhost and will NOT work on the new origin.'
Warn 'That is the origin binding doing its job. Enrol once more on the real URL.'
Warn 'To go back to local: copy .env.backup over .env and restart.'
Write-Host ''
