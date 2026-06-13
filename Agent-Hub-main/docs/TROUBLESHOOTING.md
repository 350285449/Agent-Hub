# Troubleshooting

Run:

```powershell
agent-hub doctor
```

For a machine-level setup check before the backend can start, run:

```powershell
.\scripts\check-requirements.ps1 -IncludeExtension
```

The VS Code extension exposes the same flow as `Agent Hub: Check Requirements`
and as buttons in the sidebar Setup list.

The doctor report includes config path, backend version, Python runtime,
install checks, dependency checks, backend reachability, generated backend
snapshot status, enabled providers, missing API keys, local model servers,
Cline/Claude endpoints, approval mode, safe mode, token mode, and likely fixes.
Use `agent-hub doctor --json` when filing an issue; the JSON output includes a
`runtime_dependency_audit` row and optional `release_dependency:*` rows so you
can tell whether a local install problem is runtime-related or release-tooling
related.

Useful endpoints:

- `GET /health`
- `GET /limits`
- `GET /usage`
- `GET /permissions`
- `GET /metrics`
- `GET /debug/context`
- `POST /debug/request`

Common fixes:

- Missing Python/Node/npm/VS Code CLI: run the requirement checker above and use
  its install/open button, then restart the terminal or VS Code if PATH changed.
- No usable model: enable a provider, set the missing API key, or start Ollama
  or LM Studio.
- Ollama offline: run `ollama serve`, then `agent-hub local-models`, and confirm
  `http://127.0.0.1:11434/api/tags` is reachable from the same machine.
- Backend not running: click `Start Server` in the sidebar.
- Backend missing from VSIX: run `npm run prepare-backend` in
  `vscode-extension/`, then package again. `npm run package`,
  `npm run publish`, and VSCE prepublish all regenerate the snapshot.
- Release validation cannot import release tooling: install the release extra
  with `python -m pip install -e ".[release]"`.
- Port conflict: stop the old server or change `agentHub.serverUrl`.
- Cline empty context: use base URL ending in `/v1`, model `agent-hub-coding`,
  and keep `cline_compatibility_mode=true`.
- Echo disabled: configure a real provider or set `debug_echo_enabled=true`
  only for diagnostics.

## Cline `Invalid API Response`

This usually means the upstream provider returned an empty body, malformed JSON,
truncated SSE chunk, invalid tool-call arguments, or a partial
OpenAI-compatible response.

Recommended stability settings:

```json
{
  "cline_compatibility_mode": true,
  "force_compatibility_streaming": true,
  "tool_loop_enabled_for_cline": false,
  "compatibility_mode": {
    "minimal_tool_schema": true,
    "reduced_repo_context": true,
    "max_context_tokens": null
  }
}
```

For a failing provider, temporarily enable:

```json
{
  "debug_raw_provider_responses": true,
  "tool_loop_debug": true
}
```

Reproduce the issue, then inspect `.agent-hub/debug/` and
`.agent-hub/state/routing_decisions.jsonl`. Also check
`.agent-hub/state/events.jsonl` for `provider.failed`, `router.fallback`,
`stream.failed`, and `context.truncated`. Debug traces are redacted and
truncated, but still show raw provider JSON, malformed stream chunks, finish
reasons, tool calls, request IDs, provider request IDs, stream IDs, routing mode,
and token estimates.

If the failure happens only on long or multi-file tasks, set an explicit
`compatibility_mode.max_context_tokens`, reduce `repo_context_max_files`, or use
a provider with a larger reliable context window.

## Backend Snapshot Drift

Packaged VS Code builds use `vscode-extension/backend`. If release validation
reports backend drift, regenerate the snapshot from the repository root:

```powershell
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
python scripts/validate_release.py
```

Do not edit files inside `vscode-extension/backend` directly; edit the canonical
backend files under `agent_hub/`, then regenerate.
