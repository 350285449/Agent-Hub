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
    "max_context_tokens": 12000
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

If the failure happens only on long or multi-file tasks, lower
`compatibility_mode.max_context_tokens`, reduce `repo_context_max_files`, or use
a provider with a larger reliable context window.
