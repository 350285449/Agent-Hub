# Continue Setup

Use Agent-Hub as an OpenAI-compatible provider.

```json
{
  "title": "Agent-Hub",
  "provider": "openai",
  "model": "agent-hub-coding",
  "apiBase": "http://127.0.0.1:8787/v1",
  "apiKey": "local-agent-hub-token"
}
```

Start the backend:

```sh
python -m agent_hub serve
```

Agent-Hub preserves Continue's OpenAI response shape and streams with
`stream=true`. Client-provided tools are passed through unless
`agent_hub.auto_execute_tools=true` is set.

## Approval Compatibility

Continue cannot respond to interactive provider-approval prompts. If a request
routes workspace context to a cloud provider and receives
`agent_hub_permission_required`, enable non-interactive compatibility for
trusted IDE routing:

```json
{
  "approval_mode": "auto",
  "cline_compatibility_mode": true,
  "tool_loop_enabled": true
}
```

This allows trusted cloud providers such as OpenAI, Anthropic, Gemini, Groq,
OpenRouter, and Ollama Cloud without pausing for an approval prompt. Agent-Hub
still logs the route decision to `.agent-hub/state/security_audit.jsonl`, keeps
tool permission checks active, blocks dangerous shell/file actions, enforces
workspace path restrictions, and may still block unknown external endpoints or
requests containing secrets.
