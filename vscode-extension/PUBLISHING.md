# Agent Hub VS Code Extension Publishing

Use this checklist to package, smoke-test, and publish the VS Code extension in
`vscode-extension/`. The canonical release flow is documented in
`docs/PUBLISHING.md`, and release metadata comes from `release.json`.

## Current Release

- Extension ID: `agent-hub.agent-hub-vscode`
- Package name: `agent-hub-vscode`
- Current version: read from `vscode-extension/package.json`
- Expected VSIX: `vscode-extension/agent-hub-vscode-<version>.vsix`

## Prerequisites

Install these before publishing:

- Node.js 20 or newer
- Python 3.11 or newer
- A VS Code-compatible CLI, such as `code`, `code-insiders`, or `codium`
- Marketplace publish access for publisher `agent-hub`
- A VSCE personal access token in `VSCE_PAT`, or Microsoft Entra auth with
  `vsce publish --azure-credential`

Microsoft's current VS Code publishing guide is here:
<https://code.visualstudio.com/api/working-with-extensions/publishing-extension>.

On Windows, use `npm.cmd` if PowerShell blocks `npm.ps1` because script
execution is disabled.

## Preflight

From the repository root:

```powershell
git status --short
node --version
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
python scripts/validate_release.py
python scripts/package_clean.py
cd vscode-extension
npm.cmd ci
npm.cmd run check
npm.cmd run check:version
```

The worktree should contain only intentional release changes before publishing.

## Build The VSIX

From the repository root on Windows:

```powershell
.\install-extension.ps1 --package-only
```

On macOS or Linux:

```sh
sh ./install-extension.sh --package-only
```

This runs the backend staging step and creates:

```text
vscode-extension/agent-hub-vscode-<version>.vsix
```

Validate the packaged archive before installing or publishing:

```powershell
python .\scripts\validate_vsix_cleanliness.py
```

To remove stale local VSIX files and force a fresh package:

```powershell
python .\scripts\package_clean.py --apply --include-current-vsix
cd vscode-extension
npm.cmd run package
```

## Manual CI Release

The GitHub Actions workflow `Manual VSIX Release` can be started with
`workflow_dispatch`. It stamps CI build metadata into `release.json`,
regenerates the backend snapshot, validates release metadata, runs tests,
packages the VSIX, validates the archive, uploads the VSIX as a workflow
artifact, and can create or update a GitHub Release tagged as
`v<extension-version>` with the VSIX attached. It does not publish to the
Marketplace.

## Smoke-Test Locally

Install the built VSIX into VS Code:

```powershell
.\install-extension.ps1 --vsix .\vscode-extension\agent-hub-vscode-<version>.vsix
```

Reload VS Code, open a workspace, and run:

- `Agent Hub: Open Chat`
- `Agent Hub: Show Status`
- `Agent Hub: Research Web`, if you want to verify the bundled backend path

## Publish

To publish the version from `package.json`:

```powershell
cd vscode-extension
$env:VSCE_PAT = "<marketplace-personal-access-token>"
npm.cmd run publish
```

To publish the already-built VSIX instead:

```powershell
cd vscode-extension
$env:VSCE_PAT = "<marketplace-personal-access-token>"
npx.cmd vsce publish --packagePath agent-hub-vscode-<version>.vsix --allow-missing-repository
```

If the Marketplace reports that the current version already exists, choose a new version,
update `package.json`, update `package-lock.json`, add changelog notes, rebuild
the VSIX, and publish again. For a patch release:

```powershell
cd vscode-extension
npm.cmd version patch --no-git-tag-version
npm.cmd run package
npm.cmd run publish
```

## Verify

After publishing, check the Marketplace entry:

```powershell
cd vscode-extension
npx.cmd vsce show agent-hub.agent-hub-vscode
```

Confirm the displayed version matches the release, then commit the release notes,
manifest, lockfile, and any generated VSIX you intend to keep in the repository.

## Troubleshooting Auth

If publishing fails with `TF400813` or "Personal Access Token verification has
failed", the token or Microsoft account does not have access to publisher
`agent-hub`.

Fix it by creating a new Azure DevOps personal access token with:

- Organization: `All accessible organizations`
- Scopes: `Custom defined` -> `Marketplace` -> `Manage`
- The same Microsoft account that can manage
  <https://marketplace.visualstudio.com/manage/publishers/>

Then either log in again:

```powershell
cd vscode-extension
npx.cmd vsce login agent-hub
```

or publish with the token in the current shell:

```powershell
cd vscode-extension
$env:VSCE_PAT = "<marketplace-personal-access-token>"
npx.cmd vsce publish --packagePath agent-hub-vscode-<version>.vsix --allow-missing-repository
```
