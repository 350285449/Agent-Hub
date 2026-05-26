# Cline Setup

Agent Hub works as an OpenAI-compatible backend for Cline.

Recommended values:

```json
{
  "apiProvider": "openai-compatible",
  "openAiBaseUrl": "http://127.0.0.1:8787/v1",
  "openAiApiKey": "local-agent-hub-token",
  "openAiModelId": "agent-hub-coding",
  "model": "agent-hub-coding"
}
```

Use `Agent Hub: Copy Cline Config` from VS Code to copy the current base URL.
Use `Agent Hub: Test Cline Connection` to verify that structured content,
`task_progress`, TODO state, active files, and tool results are preserved before
Cline sends a real model request.

Agent-Hub preserves Cline's client-provided tool schema by default. Built-in
Agent-Hub tools are executed by the backend only when Agent-Hub owns the tool
schema or `agent_hub.auto_execute_tools=true` is sent.

Diagnostics:

```powershell
agent-hub inspect-request .\cline-payload.json --api-shape openai-chat
curl http://127.0.0.1:8787/debug/context
```

If Cline shows empty context, confirm that `cline_compatibility_mode` is `true`
in `agent-hub.config.json` and that Cline is pointed at `/v1`.
