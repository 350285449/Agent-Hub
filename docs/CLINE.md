# Cline Setup

Agent Hub works as an OpenAI-compatible backend for Cline.

Recommended values:

```json
{
  "apiProvider": "openai-compatible",
  "openAiBaseUrl": "http://127.0.0.1:8787/v1",
  "openAiApiKey": "agent-hub-local",
  "openAiModelId": "agent-hub-coding",
  "model": "agent-hub-coding"
}
```

Use `Agent Hub: Copy Cline Config` from VS Code to copy the current base URL.
Use `Agent Hub: Test Cline Connection` to verify that structured content,
`task_progress`, TODO state, active files, and tool results are preserved before
Cline sends a real model request.

Diagnostics:

```powershell
agent-hub inspect-request .\cline-payload.json --api-shape openai-chat
curl http://127.0.0.1:8787/debug/context
```

If Cline shows empty context, confirm that `cline_compatibility_mode` is `true`
in `agent-hub.config.json` and that Cline is pointed at `/v1`.
