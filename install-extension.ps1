$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $Root "vscode-extension\scripts\install-extension.js"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 20 or newer is required to package and install the VS Code extension."
}

& node $Installer @args
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
