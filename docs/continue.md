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
