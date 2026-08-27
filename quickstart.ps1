#Requires -Version 5.1
<#
    ENYGMA quickstart for Windows.

    Runs on: your machine, in PowerShell.

        .\quickstart.cmd              local only, on http://localhost:4073
        .\quickstart.cmd -Tunnel      the same, plus a public https URL

    Written for Windows PowerShell 5.1, which is what ships with Windows. It uses
    no "&&", no ternaries and no null-coalescing, because 5.1 has none of them.
#>
param(
    [int]$Port = 4073,
    [switch]$Tunnel
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Say($text) { Write-Host "-> $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "" ; Write-Host $text -ForegroundColor Red ; exit 1 }

# --- find a real Python 3 -------------------------------------------------
# The Microsoft Store ships a stub called python.exe that opens the Store
# instead of running anything, so check that the version actually comes back.
$pyExe = $null
$pyArgs = @()
foreach ($candidate in @('py', 'python', 'python3')) {
    if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
    $tryArgs = @()
    if ($candidate -eq 'py') { $tryArgs = @('-3') }
    try {
        $version = & $candidate @tryArgs '--version' 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -match 'Python 3\.(\d+)') {
            if ([int]$Matches[1] -lt 10) { continue }
            $pyExe = $candidate
            $pyArgs = $tryArgs
            Say "using $candidate ($version)"
            break
        }
    } catch { }
}
if (-not $pyExe) {
    Fail @"
No usable Python 3.10 or newer was found.

Install it from https://www.python.org/downloads/windows/ and tick
"Add python.exe to PATH" in the installer, then open a new PowerShell and
run this again.

If 'python' opens the Microsoft Store instead of running, turn off the alias:
Settings > Apps > Advanced app settings > App execution aliases.
"@
}

# --- virtual environment --------------------------------------------------
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Say 'creating .venv'
    & $pyExe @pyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the virtual environment.' }
}
# Calling the venv's python.exe directly avoids Activate.ps1 and the execution
# policy question entirely.

Say 'installing dependencies (a minute the first time)'
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed. The output above says why.' }

# --- configuration --------------------------------------------------------
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envPath)) {
    Say 'writing .env for local use'
    $secret = (& $venvPython -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
    $lines = @(
        "ENYGMA_PORT=$Port",
        'ENYGMA_HOST=127.0.0.1',
        'ENYGMA_RP_ID=localhost',
        "ENYGMA_ORIGIN=http://localhost:$Port",
        "ENYGMA_SESSION_SECRET=$secret",
        'ENYGMA_INSECURE_COOKIES=1',
        'ENYGMA_PIPELINE=stub',
        'ENYGMA_HINOTES_ENABLED=0'
    )
    # No BOM: a byte order mark at the front of the first line would become part
    # of the first key name.
    [System.IO.File]::WriteAllLines($envPath, $lines, (New-Object System.Text.UTF8Encoding($false)))
}

Say 'loading .env'
foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
    $trimmed = $line.Trim()
    if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
    $split = $trimmed.IndexOf('=')
    if ($split -lt 1) { continue }
    $name = $trimmed.Substring(0, $split).Trim()
    $value = $trimmed.Substring($split + 1).Trim()
    Set-Item -Path ("Env:" + $name) -Value $value
}

# --- checks ---------------------------------------------------------------
& $venvPython tools\check_tokens.py
if ($LASTEXITCODE -ne 0) { Fail 'The token lint failed.' }
& $venvPython -m pytest tests -q
if ($LASTEXITCODE -ne 0) { Fail 'Tests failed. Nothing is started when they do.' }

# --- optional public URL --------------------------------------------------
if ($Tunnel) {
    if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
        Write-Host ''
        Write-Host 'cloudflared is not installed. Install it with:' -ForegroundColor Yellow
        Write-Host '    winget install --id Cloudflare.cloudflared'
        Write-Host 'then open a new PowerShell and run this again with -Tunnel.'
    } else {
        Say 'opening a public tunnel; watch for the trycloudflare.com URL'
        Write-Host '   A passkey is bound to one origin. Put that hostname in' -ForegroundColor Yellow
        Write-Host '   ENYGMA_RP_ID and ENYGMA_ORIGIN in .env and restart, or the' -ForegroundColor Yellow
        Write-Host '   unlock will refuse.' -ForegroundColor Yellow
        Start-Process -NoNewWindow cloudflared -ArgumentList @('tunnel', '--url', "http://localhost:$Port")
    }
}

Write-Host ''
Write-Host "ENYGMA is on http://localhost:$Port" -ForegroundColor Green
Write-Host '  Open /lock and create a passkey, then drop an audio file on /meetings.'
Write-Host '  Ctrl+C stops it.'
Write-Host ''
& $venvPython -m uvicorn src.main:app --host $env:ENYGMA_HOST --port $Port
