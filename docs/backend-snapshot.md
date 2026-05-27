# Backend Snapshot Duplication

`agent_hub/` is the canonical Python backend source.

`vscode-extension/backend/agent_hub/` is a generated VS Code packaging snapshot.
It is refreshed by:

```powershell
python scripts/generate_backend_snapshot.py
```

The VS Code packaging command `npm.cmd run prepare-backend` delegates to the
same generator.

The snapshot exists so a packaged VSIX can bundle the backend without requiring
an editable repository checkout. Do not make feature fixes directly in
`vscode-extension/backend/agent_hub/`; make them in `agent_hub/`, then regenerate
the snapshot during packaging.

To prevent drift before release:

```powershell
python -m compileall -q agent_hub
python -m unittest discover -s tests
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
python scripts/validate_release.py
```

The generator writes `vscode-extension/backend/SNAPSHOT.json`, a deterministic
manifest with file hashes and a tree checksum. `validate_backend_drift.py`
recomputes those hashes from `agent_hub/`, `pyproject.toml`, `README.md`, and
`release.json` and fails if any snapshot file differs, is missing, or is
unexpected. It also fails if required package files are missing or forbidden
files such as `.env`, cache files, test files, `node_modules`, old `.vsix`
packages, or temporary files appear in the snapshot.

CI regenerates the snapshot before validation so clean checkouts can produce
the same package structure deterministically. Release packaging uses the same
generator through `npm.cmd run prepare-backend`.

Phase 10 should decide whether the generated snapshot remains an ignored local
artifact or moves to a wheel-based backend package.
