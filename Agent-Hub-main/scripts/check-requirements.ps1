param(
    [switch]$IncludeExtension,
    [switch]$IncludeOptional,
    [switch]$Json,
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Test-CommandAvailable {
    param([string]$Command)
    return [bool](Get-Command $Command -ErrorAction SilentlyContinue)
}

function Invoke-Capture {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )
    try {
        $output = & $Command @Arguments 2>&1
        return @{
            ok = $LASTEXITCODE -eq 0
            output = ($output -join "`n").Trim()
        }
    }
    catch {
        return @{
            ok = $false
            output = $_.Exception.Message
        }
    }
}

function Get-PythonStatus {
    $probe = "import sys, venv; print('.'.join(map(str, sys.version_info[:3]))); raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    $candidates = @()
    foreach ($path in @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root ".venv\bin\python"),
        (Join-Path $Root ".venv-check\Scripts\python.exe"),
        (Join-Path $Root ".venv-check\bin\python")
    )) {
        if (Test-Path $path) {
            $candidates += ,@($path)
        }
    }
    $candidates += ,@("py", "-3.14")
    $candidates += ,@("py", "-3.13")
    $candidates += ,@("py", "-3.12")
    $candidates += ,@("py", "-3.11")
    $candidates += ,@("py", "-3")
    $candidates += ,@("python")
    $candidates += ,@("python3")
    foreach ($candidate in $candidates) {
        $command = $candidate[0]
        $arguments = @()
        if ($candidate.Length -gt 1) {
            $arguments = $candidate[1..($candidate.Length - 1)]
        }
        $result = Invoke-Capture $command ($arguments + @("-c", $probe))
        if ($result.ok) {
            return @{
                name = "Python 3.11+"
                id = "python"
                ok = $true
                required = $true
                version = $result.output.Split("`n")[0]
                detail = "Found with: $($candidate -join ' ')"
                install = "winget install -e --id Python.Python.3.12"
                url = "https://www.python.org/downloads/"
            }
        }
    }
    return @{
        name = "Python 3.11+"
        id = "python"
        ok = $false
        required = $true
        version = ""
        detail = "Required for the Agent Hub backend and virtual environment setup."
        install = "winget install -e --id Python.Python.3.12"
        url = "https://www.python.org/downloads/"
    }
}

function Get-NodeStatus {
    if (-not (Test-CommandAvailable "node")) {
        return @{
            name = "Node.js 20+"
            id = "node"
            ok = $false
            required = [bool]$IncludeExtension
            version = ""
            detail = "Required to package/install the VS Code extension and install Codex CLI."
            install = "winget install -e --id OpenJS.NodeJS.LTS"
            url = "https://nodejs.org/en/download"
        }
    }
    $result = Invoke-Capture "node" @("-p", "process.versions.node")
    $version = $result.output.Split("`n")[0]
    $major = (& node -p "process.versions.node.split('.')[0]") -as [int]
    return @{
        name = "Node.js 20+"
        id = "node"
        ok = $major -ge 20
        required = [bool]$IncludeExtension
        version = $version
        detail = if ($major -ge 20) { "Found on PATH." } else { "Found $version, but Agent Hub needs Node.js 20 or newer." }
        install = "winget install -e --id OpenJS.NodeJS.LTS"
        url = "https://nodejs.org/en/download"
    }
}

function Get-NpmStatus {
    if (-not (Test-CommandAvailable "npm")) {
        return @{
            name = "npm"
            id = "npm"
            ok = $false
            required = [bool]$IncludeExtension
            version = ""
            detail = "Required for extension packaging and Codex CLI installation."
            install = "winget install -e --id OpenJS.NodeJS.LTS"
            url = "https://nodejs.org/en/download"
        }
    }
    $result = Invoke-Capture "npm" @("--version")
    return @{
        name = "npm"
        id = "npm"
        ok = $result.ok
        required = [bool]$IncludeExtension
        version = $result.output.Split("`n")[0]
        detail = "Found on PATH."
        install = "winget install -e --id OpenJS.NodeJS.LTS"
        url = "https://nodejs.org/en/download"
    }
}

function Get-CodeStatus {
    $candidates = @("code", "code-insiders", "codium")
    foreach ($candidate in $candidates) {
        $result = Invoke-Capture $candidate @("--version")
        if ($result.ok) {
            return @{
                name = "VS Code CLI"
                id = "vscode_cli"
                ok = $true
                required = [bool]$IncludeExtension
                version = $result.output.Split("`n")[0]
                detail = "Found with: $candidate"
                install = "winget install -e --id Microsoft.VisualStudioCode"
                url = "https://code.visualstudio.com/download"
            }
        }
    }
    return @{
        name = "VS Code CLI"
        id = "vscode_cli"
        ok = $false
        required = [bool]$IncludeExtension
        version = ""
        detail = "Required to install the built VSIX from scripts. In VS Code, you can also run Shell Command: Install 'code' command in PATH."
        install = "winget install -e --id Microsoft.VisualStudioCode"
        url = "https://code.visualstudio.com/download"
    }
}

function Get-OllamaStatus {
    $result = Invoke-Capture "ollama" @("--version")
    return @{
        name = "Ollama"
        id = "ollama"
        ok = $result.ok
        required = $false
        version = if ($result.ok) { $result.output.Split("`n")[0] } else { "" }
        detail = if ($result.ok) { "Found on PATH." } else { "Optional local-model runtime." }
        install = ""
        url = "https://ollama.com/download"
    }
}

function Get-CodexStatus {
    $result = Invoke-Capture "codex" @("--version")
    return @{
        name = "Codex CLI"
        id = "codex_cli"
        ok = $result.ok
        required = $false
        version = if ($result.ok) { $result.output.Split("`n")[0] } else { "" }
        detail = if ($result.ok) { "Found on PATH." } else { "Optional no-key Codex routing helper." }
        install = "npm install -g @openai/codex@latest"
        url = "https://www.npmjs.com/package/@openai/codex"
    }
}

function Get-RequirementRows {
    $rows = @(
        Get-PythonStatus
    )
    if ($IncludeExtension) {
        $rows += Get-NodeStatus
        $rows += Get-NpmStatus
        $rows += Get-CodeStatus
    }
    if ($IncludeOptional) {
        $rows += Get-OllamaStatus
        $rows += Get-CodexStatus
    }
    return $rows
}

function Format-Status {
    param([hashtable]$Row)
    if ($Row.ok) {
        return "OK"
    }
    if ($Row.required) {
        return "MISSING"
    }
    return "OPTIONAL"
}

function Show-InstallPrompt {
    param([hashtable]$Row)
    if ($Row.ok -or (-not $Row.install -and -not $Row.url)) {
        return
    }

    $message = "$($Row.name) is missing.`n`n$($Row.detail)"
    $title = "Agent Hub setup"
    $buttonText = if ($Row.install) { "Install" } else { "Open Download" }
    $opened = $false

    if ($IsWindows -or $env:OS -eq "Windows_NT") {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $choice = [System.Windows.Forms.MessageBox]::Show(
            "$message`n`nClick Yes to $buttonText.",
            $title,
            [System.Windows.Forms.MessageBoxButtons]::YesNo,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($choice -ne [System.Windows.Forms.DialogResult]::Yes) {
            return
        }
    }
    else {
        Write-Host ""
        Write-Host "$message"
        $answer = Read-Host "Open/install now? [y/N]"
        if ($answer -notmatch "^[Yy]") {
            return
        }
    }

    if ($Row.install -and (Test-CommandAvailable "winget") -and $Row.install.StartsWith("winget ")) {
        Start-Process "powershell.exe" -ArgumentList @("-NoExit", "-NoProfile", "-Command", $Row.install) | Out-Null
        $opened = $true
    }
    elseif ($Row.id -eq "codex_cli" -and (Test-CommandAvailable "npm")) {
        Start-Process "powershell.exe" -ArgumentList @("-NoExit", "-NoProfile", "-Command", "$($Row.install); if (`$LASTEXITCODE -eq 0) { codex login }") | Out-Null
        $opened = $true
    }

    if (-not $opened -and $Row.url) {
        Start-Process $Row.url | Out-Null
    }
}

$rows = @(Get-RequirementRows)
$missingRequired = @($rows | Where-Object { $_.required -and -not $_.ok })

if ($Json) {
    [pscustomobject]@{
        object = "agent_hub.requirements"
        ok = $missingRequired.Count -eq 0
        include_extension = [bool]$IncludeExtension
        include_optional = [bool]$IncludeOptional
        requirements = $rows
        missing_required = $missingRequired
    } | ConvertTo-Json -Depth 6
}
else {
    Write-Host "Agent Hub requirement check"
    Write-Host ""
    $rows |
        ForEach-Object {
            [pscustomobject]@{
                Status = Format-Status $_
                Name = $_["name"]
                Version = $_["version"]
                Required = $_["required"]
                Detail = $_["detail"]
            }
        } |
        Format-Table -AutoSize
}

if (-not $NoPrompt) {
    foreach ($row in $rows) {
        if (-not $row.ok -and ($row.required -or $IncludeOptional)) {
            Show-InstallPrompt $row
        }
    }
}

if ($missingRequired.Count -gt 0) {
    if (-not $Json) {
        Write-Host ""
        Write-Host "Install the missing required item(s), reopen your terminal if PATH changed, then rerun the installer."
    }
    exit 1
}

exit 0
