$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Config = Join-Path $Root "agent-hub.config.json"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 or newer is required and was not found on PATH."
}

Push-Location $Root
try {
    if (-not (Test-Path $Python)) {
        Write-Host "Creating .venv..."
        python -m venv $Venv
    }

    Write-Host "Installing Agent-Hub into .venv..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e $Root

    if (-not (Test-Path $Config)) {
        Write-Host "Creating agent-hub.config.json..."
        & $Python -m agent_hub init
    }

    Write-Host ""
    & $Python -m agent_hub doctor
    Write-Host ""
    Write-Host "Ready. Start the server with: .\start-agent-hub.ps1"
    Write-Host "Or chat in this terminal with: .\.venv\Scripts\agent-hub.exe chat --allow-shell-tools"
    Write-Host "To install the VS Code extension from this checkout: .\install-extension.ps1"
}
finally {
    Pop-Location
}
