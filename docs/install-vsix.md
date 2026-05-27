# Install From VSIX

Build or install the packaged VS Code extension:

```sh
python scripts/package_clean.py
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
python scripts/validate_release.py
cd vscode-extension
npm ci
npm run compile
npm run check:version
npm run package
python ../scripts/validate_vsix_cleanliness.py
code --install-extension agent-hub-vscode-<version>.vsix
```

Start the backend from the repository or from the extension command:

```sh
python -m agent_hub serve
```

Cline:

- Base URL: `http://127.0.0.1:8787/v1`
- API key: `local-agent-hub-token`
- Model: `agent-hub-coding`

Continue:

```json
{
  "title": "Agent-Hub",
  "provider": "openai",
  "model": "agent-hub-coding",
  "apiBase": "http://127.0.0.1:8787/v1",
  "apiKey": "local-agent-hub-token"
}
```

Packaged builds exclude local config, logs, provider health state, `.agent-hub`
state folders, and existing `.vsix` artifacts. Run
`python scripts/validate_vsix_cleanliness.py <path-to.vsix>` from the repository
root to inspect a package for nested VSIX files, `node_modules`, `.env` files,
backup configs, local absolute paths, secret-looking strings, temporary files,
development artifacts, test files, and oversized files.

Release metadata comes from `release.json`; avoid hardcoding versioned VSIX
names in release docs.

Use `python scripts/validate_vsix_cleanliness.py --check-source` when preparing
a release branch if you also want to fail on stray `.vsix` files in the source
checkout.

The manual GitHub Actions release workflow performs the same validation and
uploads the generated VSIX as an artifact. It does not publish automatically;
download and inspect the artifact before running Marketplace publishing
commands manually.
