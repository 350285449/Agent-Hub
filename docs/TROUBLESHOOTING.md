# Troubleshooting

Run:

```powershell
agent-hub doctor
```

The doctor report includes config path, backend version, Python runtime,
enabled providers, missing API keys, local model servers, Cline/Claude endpoints,
approval mode, safe mode, token mode, and likely fixes.

Useful endpoints:

- `GET /health`
- `GET /limits`
- `GET /usage`
- `GET /permissions`
- `GET /metrics`
- `GET /debug/context`
- `POST /debug/request`

Common fixes:

- No usable model: enable a provider, set the missing API key, or start Ollama
  or LM Studio.
- Backend not running: click `Start Server` in the sidebar.
- Port conflict: stop the old server or change `agentHub.serverUrl`.
- Cline empty context: use base URL ending in `/v1`, model `agent-hub-coding`,
  and keep `cline_compatibility_mode=true`.
- Echo disabled: configure a real provider or set `debug_echo_enabled=true`
  only for diagnostics.
