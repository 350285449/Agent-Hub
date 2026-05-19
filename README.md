# Agent-Hub

Agent-Hub is a local routing layer for agent-style LLM requests. It accepts JSON,
chooses a configured agent/model, and fails over to the next agent when a provider
is out of quota, rate limited, overloaded, or cannot handle the context size.

It is designed for legitimate API/local-model routing. It does not automate
bypassing free-tier limits or scraping web UIs. Add providers you are allowed to
use through API keys or local OpenAI-compatible servers.

## What It Runs

- Local HTTP server on `127.0.0.1:8787`
- OpenAI-compatible endpoint: `POST /v1/chat/completions`
- Anthropic-compatible endpoint: `POST /v1/messages`
- Native endpoint: `POST /v1/agent`
- JSON file inbox: `.agent-hub/inbox/*.json`
- Session logs: `.agent-hub/state/sessions/*.json`

## Quick Start

```powershell
Copy-Item agent-hub.config.example.json agent-hub.config.json
$env:ANTHROPIC_API_KEY = "your-anthropic-key"
$env:OPENAI_API_KEY = "your-openai-key"
python -m agent_hub serve --watch-inbox
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health
```

Native request:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/v1/agent `
  -Method Post `
  -ContentType "application/json" `
  -Body (@{
    session_id = "demo"
    route = "coding"
    task = "Write a Python function that validates an email address."
    max_tokens = 800
  } | ConvertTo-Json)
```

OpenAI-compatible clients can point their base URL at:

```text
http://127.0.0.1:8787/v1
```

Anthropic-compatible clients can call:

```text
http://127.0.0.1:8787/v1/messages
```

## JSON Inbox

Drop a JSON task into `.agent-hub/inbox`:

```powershell
Copy-Item examples/task.json .agent-hub/inbox/task.json
python -m agent_hub once
Get-Content .agent-hub/outbox/task.response.json
```

The same request context is sent to each candidate agent in order. If `claude-coder`
returns a quota/rate/context error, Agent-Hub records that event and retries with
`openai-coder`, then `local-coder`.

Native JSON requests keep session history by default when `session_id` is reused.
OpenAI- and Anthropic-compatible requests only use stored session history when
`agent_hub.use_session_history` is set to `true`, because most API clients already
send their own conversation history.

## Config

Routes are ordered lists of agents. Keyword routes can steer coding work to coder
models while leaving a default route for everything else.

```json
{
  "default_route": ["claude-coder", "openai-coder", "local-coder"],
  "routes": [
    {
      "name": "coding",
      "keywords": ["code", "bug", "fix", "refactor", "test", "repo"],
      "agents": ["claude-coder", "openai-coder", "local-coder"]
    }
  ]
}
```

Supported providers:

- `anthropic` for Claude Messages API
- `openai` for OpenAI Chat Completions
- `openai-compatible` for local servers such as LM Studio, Ollama-compatible
  gateways, LocalAI, or vLLM gateways exposing `/v1/chat/completions`
- `echo` for local smoke tests without API keys

## Notes

- Streaming is currently bridged as one server-sent event containing the completed
  response, so clients that require true token streaming may still need adapter work.
- Tool schemas are forwarded for OpenAI-compatible requests. Cross-provider tool
  translation is intentionally conservative because vendor tool formats differ.
- Model IDs in the example config are placeholders you should replace with models
  your accounts/local servers actually expose.

API references checked while building this:

- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat/create-chat-completion
- Anthropic Messages: https://docs.anthropic.com/en/api/messages-examples
