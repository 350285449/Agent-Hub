# Publishing

`release.json` is the release metadata source for Agent Hub packaging. It
records the VS Code extension version, Python backend version, protocol/API
compatibility version, minimum supported backend version, and release timestamp.
Use `python scripts/sync_version.py <version>` before release packaging so
`release.json`, `pyproject.toml`, `agent_hub/version.py`, and VS Code extension
metadata stay aligned.
CI may stamp build metadata into `release.json` during a workflow run:
`commit_sha`, `build_timestamp_utc`, and `git_tag`.

## Canonical Layout

- `agent_hub/` is the canonical backend source.
- `vscode-extension/backend/agent_hub/` is a generated snapshot for VSIX builds.
- `vscode-extension/package.json` is the VS Code extension metadata source.
- `pyproject.toml` and `agent_hub/version.py` are the Python backend version
  sources and must agree.

## Release Flow

From the repository root:

```powershell
python -m pip install -e ".[test,dev,release]"
python scripts/package_clean.py
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
python scripts/check_config_reference.py
python scripts/validate_release.py
cd vscode-extension
npm run prepare-backend
npm.cmd run check
npm.cmd run package
```

The generated VSIX should be named:

```text
vscode-extension/agent-hub-vscode-<version>.vsix
```

To remove stale local VSIX packages before creating a fresh artifact:

```powershell
python scripts/package_clean.py --apply --include-current-vsix
```

Then run `npm.cmd run package` from `vscode-extension`.
The package and publish scripts both run `prepare-backend`, and
`vscode:prepublish` also regenerates and validates the backend snapshot for
direct VSCE packaging.

## CI Validation

`.github/workflows/ci.yml` runs on pull requests, pushes, and manual dispatch.
It installs with `npm ci` to verify `package-lock.json`, installs the Python
`test` and `release` extras, compiles Python, validates config drift, generates
and validates the backend snapshot, validates `release.json`, runs packaging
pytest checks, runs the default `pytest -m "not integration and not stress"`
lane, checks VS Code extension syntax, packages a VSIX, and validates VSIX
cleanliness with source-tree artifact checks. Integration and stress tests are
separate pytest lanes:

```powershell
pytest -m integration
pytest -m stress
```

## Manual Release Workflow

`.github/workflows/release.yml` is intentionally manual. It stamps CI build
metadata, validates the release, runs tests, regenerates the backend snapshot,
packages a VSIX, validates the artifact, uploads the VSIX as a workflow
artifact, and can create or update a GitHub Release for the extension version.
The GitHub Release step tags the selected commit as `v<extension-version>` and
attaches the generated VSIX. It does not publish to the Marketplace.

After downloading the artifact or release asset and inspecting it locally,
publish manually from `vscode-extension` with the Marketplace tooling and the
expected publisher credentials.

## Packaging Guarantees

VSIX packaging excludes old `.vsix` files, `.env` files, local configs, logs,
state folders, test artifacts, cache folders, temporary files, and
`node_modules` when runtime dependencies are not needed. Package size and
secret-looking strings are checked by:

```powershell
python scripts/validate_vsix_cleanliness.py
```

Run this source-tree check before a release cleanup branch or after packaging:

```powershell
python scripts/validate_vsix_cleanliness.py --check-source
```

## Drift Prevention

`vscode-extension/backend/SNAPSHOT.json` stores deterministic checksums for the
generated backend snapshot. `validate_backend_drift.py` fails when security
fixes or packaging changes land in `agent_hub/` but the VS Code snapshot was not
regenerated.

`validate_release.py` also checks extension version metadata, backend version
metadata, generated config reference freshness, backend snapshot drift, release
doc placeholders, dependency declarations, package-lock version consistency,
extension packaging hooks, and the current VSIX if it exists.

## Manual Publishing

The manual release workflow produces an artifact only. To publish:

```powershell
cd vscode-extension
npm.cmd ci
npm.cmd run validate-release
npx @vscode/vsce publish --allow-missing-repository --packagePath agent-hub-vscode-<version>.vsix
```

Do this only after validating the downloaded workflow artifact.
