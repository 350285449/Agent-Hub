param(
    [switch]$WithExtension,
    [switch]$SkipBackend,
    [switch]$SkipDeps,
    [switch]$PackageOnly,
    [switch]$CheckOnly,
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$Config = Join-Path $Root "agent-hub.config.json"

function Find-Python311 {
    $candidates = @(
        @("py", "-3.14"),
        @("py", "-3.13"),
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("py", "-3"),
        @("python"),
        @("python3")
    )
    foreach ($candidate in $candidates) {
        $command = $candidate[0]
        $arguments = @()
        if ($candidate.Length -gt 1) {
            $arguments = $candidate[1..($candidate.Length - 1)]
        }
        $probe = "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        try {
            & $command @arguments -c $probe *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{ Command = $command; Args = $arguments }
            }
        }
        catch {
            continue
        }
    }
    throw "Python 3.11 or newer is required. Install Python, then rerun this script."
}

function Invoke-Python {
    param(
        [hashtable]$PythonSpec,
        [string[]]$Arguments
    )
    $allArgs = @()
    if ($PythonSpec.Args) {
        $allArgs += $PythonSpec.Args
    }
    $allArgs += $Arguments
    & $PythonSpec.Command @allArgs
}

function Test-Node20 {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        return $false
    }
    $major = (& node -p "process.versions.node.split('.')[0]") -as [int]
    return $major -ge 20
}

function Invoke-RequirementCheck {
    param([switch]$IncludeExtension)
    $script = Join-Path $Root "scripts\check-requirements.ps1"
    if (-not (Test-Path $script)) {
        return
    }
    $arguments = @()
    if ($IncludeExtension) {
        $arguments += "-IncludeExtension"
    }
    if ($NoPrompt) {
        $arguments += "-NoPrompt"
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Agent Hub requirement check failed. Install the missing required item(s), reopen your terminal if PATH changed, then rerun this installer."
    }
}

Push-Location $Root
try {
    if (-not $SkipBackend -or $WithExtension) {
        Invoke-RequirementCheck -IncludeExtension:$WithExtension
    }
    if ($CheckOnly) {
        return
    }

    if (-not $SkipBackend) {
        $PythonSpec = Find-Python311
        if (-not (Test-Path $Python)) {
            Write-Host "Creating .venv..."
            Invoke-Python $PythonSpec @("-m", "venv", $Venv)
        }

        Write-Host "Installing Agent-Hub into .venv..."
        & $Python -m pip install --upgrade pip
        & $Python -m pip install -e $Root

        if (-not (Test-Path $Config)) {
            Write-Host "Creating agent-hub.config.json..."
            & $Python -m agent_hub init --with-cloud-examples
        }

        Write-Host ""
        & $Python -m agent_hub doctor
    }

    if ($WithExtension) {
        if (-not (Test-Node20)) {
            throw "Node.js 20 or newer is required to build/install the VS Code extension."
        }
        $extensionArgs = @()
        if ($SkipDeps) {
            $extensionArgs += "--skip-deps"
        }
        if ($PackageOnly) {
            $extensionArgs += "--package-only"
        }
        Write-Host ""
        Write-Host "Packaging/installing VS Code extension..."
        & node (Join-Path $Root "vscode-extension\scripts\install-extension.js") @extensionArgs
    }

    Write-Host ""
    Write-Host "Ready."
    Write-Host "Start the server with: .\start-agent-hub.ps1"
    Write-Host "Open chat with: .\.venv\Scripts\agent-hub.exe chat --allow-shell-tools"
    Write-Host "Install the VS Code extension with: .\install-extension.ps1"
    Write-Host "Or install backend + extension together with: .\install.ps1 -WithExtension"
}
finally {
    Pop-Location
}
