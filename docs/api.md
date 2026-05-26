# API Examples

Agent-Hub exposes native and compatibility endpoints on the local server.

## OpenAI Chat Completions

```sh
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agent-hub-coding",
    "messages": [{"role": "user", "content": "Fix the failing test"}]
  }'
```

## Streaming

```sh
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "agent-hub-coding",
    "stream": true,
    "messages": [{"role": "user", "content": "Write a short plan"}]
  }'
```

The response header `X-Agent-Hub-Stream-Mode` is `native` when the selected
provider streams live chunks and `compatibility` when Agent-Hub streams a
completed response.

## Workflows

```sh
curl http://127.0.0.1:8787/v1/workflows/code \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Add validation for config loading"}]
  }'
```

## Health

```sh
curl http://127.0.0.1:8787/health
```

Health includes provider status, latency, score, cooldowns, streaming support,
limits, routing capabilities, context diagnostics, and enabled features.

## Cline

- Base URL: `http://127.0.0.1:8787/v1`
- API key: any local placeholder
- Model: `agent-hub-coding`

## Continue

Use an OpenAI-compatible model entry:

```json
{
  "title": "Agent-Hub",
  "provider": "openai",
  "model": "agent-hub-coding",
  "apiBase": "http://127.0.0.1:8787/v1",
  "apiKey": "local"
}
```
