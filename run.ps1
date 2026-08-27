#Requires -Version 5.1
# Runs on: your machine. Starts an already-installed checkout.
param([int]$Port = 0)
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host 'No .venv here. Run .\quickstart.cmd first.' -ForegroundColor Red
    exit 1
}
foreach ($line in [System.IO.File]::ReadAllLines((Join-Path $PSScriptRoot '.env'))) {
    $trimmed = $line.Trim()
    if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
    $split = $trimmed.IndexOf('=')
    if ($split -lt 1) { continue }
    Set-Item -Path ("Env:" + $trimmed.Substring(0, $split).Trim()) `
             -Value $trimmed.Substring($split + 1).Trim()
}
if ($Port -eq 0) { $Port = [int]$env:ENYGMA_PORT }
& $venvPython -m uvicorn src.main:app --host $env:ENYGMA_HOST --port $Port
