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

## Approval Errors

Cline cannot answer Agent-Hub's interactive approval prompts. If a routed model
uses Ollama Cloud, OpenRouter, OpenAI, Anthropic, Groq, Gemini, or another
hosted provider while `approval_mode` is interactive, Cline can see:

```json
{
  "error": {
    "type": "agent_hub_permission_required",
    "message": "Provider requires approval. Set approval_mode=auto or enable cline_compatibility_mode."
  }
}
```

Recommended config for Cline:

```json
{
  "approval_mode": "auto",
  "cline_compatibility_mode": true,
  "tool_loop_enabled": true
}
```

With compatibility mode enabled, trusted cloud provider routing is allowed
without an interactive prompt and an audit event is written instead. Local
providers are always allowed. Unknown external endpoints can still require
explicit approval, and requests that appear to contain secrets still trigger the
security gate.

Security protections that remain active:

- shell safety and `shell_command_policy`
- workspace path restrictions and path escape protection
- dangerous command blocking
- file/tool permission checks
- provider audit logging in `.agent-hub/state/security_audit.jsonl`

Diagnostics:

```powershell
agent-hub inspect-request .\cline-payload.json --api-shape openai-chat
curl http://127.0.0.1:8787/debug/context
```

If Cline shows empty context, confirm that `cline_compatibility_mode` is `true`
in `agent-hub.config.json` and that Cline is pointed at `/v1`.
