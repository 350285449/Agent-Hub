# Claude Code Setup

Agent Hub exposes Anthropic Messages compatibility at `/v1/messages`.

Environment-style setup:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8787
ANTHROPIC_AUTH_TOKEN=agent-hub-local
ANTHROPIC_MODEL=agent-hub-coding
```

Use `Agent Hub: Copy Claude Code Config` from VS Code to copy the current
values. Use `Agent Hub: Test Anthropic Endpoint` to verify Anthropic-shaped
message normalization without spending provider tokens.

Agent Hub preserves:

- `tool_use` blocks
- `tool_result` blocks
- structured content arrays
- task progress and TODO metadata
- recent tool chains

Permissions are enforced centrally after translation, so Claude Code cannot
bypass shell, file-write, provider, config-edit, upload, or process-spawn
approval rules.
