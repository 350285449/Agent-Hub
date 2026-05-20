# Agent-Hub

Agent-Hub is a local routing layer and lightweight workspace agent for LLM
requests. It accepts JSON, chooses a configured agent/model, can run a small
tool-using agent loop, and fails over to the next agent when a provider is out
of quota, rate limited, overloaded, or cannot handle the context size.

It is local/free-only by default: if no config file exists, Agent-Hub tries your
own OpenAI-compatible local server at `127.0.0.1:8000`, then falls back to the
built-in `echo` provider for smoke tests. It does not automate bypassing
free-tier limits or scraping web UIs. Add only providers you are allowed to use
through API keys or local OpenAI-compatible servers.

## What It Runs

- Local HTTP server on `127.0.0.1:8787`
- OpenAI-compatible endpoint: `POST /v1/chat/completions`
- Anthropic-compatible endpoint: `POST /v1/messages`
- Native endpoint: `POST /v1/agent`
- Agent workspace tools: list, read, search, and write files under `workspace_dir`
- Free-only routing and context-window preflight checks before provider calls
- JSON file inbox: `.agent-hub/inbox/*.json`
- Session logs: `.agent-hub/state/sessions/*.json`

## Quick Start

```powershell
python -m agent_hub serve --watch-inbox
```

That starts with the built-in custom local/free config. You can point it at your
own server without a config file:

```powershell
$env:AGENT_HUB_LOCAL_BASE_URL = "http://127.0.0.1:8000"
$env:AGENT_HUB_LOCAL_MODEL = "local-model"
$env:AGENT_HUB_LOCAL_CONTEXT_WINDOW = "8192"
```

To customize routes, model names, token windows, or shell tools, copy and edit
the example config:

```powershell
python -m agent_hub init --with-cloud-examples
python -m agent_hub doctor
python -m agent_hub agents
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
    mode = "agent"
    route = "coding"
    task = "Inspect this repo and explain what the app does."
    max_tokens = 800
  } | ConvertTo-Json)
```

`/v1/agent` runs the agent loop by default. Use `/v1/route` when you want a
single model call with no tool loop.

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

The same request context is sent to each candidate agent in order. While
`free_only` is enabled, Agent-Hub only uses `echo` and local/private
`openai-compatible` agents. Paid API providers such as `openai` and `anthropic`
are skipped before any network call. If your custom local endpoint is not
running, a local model is missing, or the request does not fit that model's
configured token window, Agent-Hub records that event and retries with `echo`.

Native JSON requests keep session history by default when `session_id` is
reused. OpenAI- and Anthropic-compatible requests only use stored session history
when `agent_hub.use_session_history` is set to `true`, because most API clients
already send their own conversation history.

## Agent Mode

Agent mode asks the model to respond with a small JSON protocol:

```json
{"action":"tool","tool":"read_file","args":{"path":"README.md"}}
```

or:

```json
{"action":"final","answer":"Done."}
```

The hub executes tool calls locally, feeds the result back to the model, and
continues until the model returns a final answer or `agent_max_steps` is reached.

Available tools:

- `list_files`
- `read_file`
- `search_files`
- `write_file`
- `run_command`, disabled unless `allow_shell_tools` is `true`

## Config

Routes are ordered lists of agents. Keyword routes can steer coding work to coder
models while leaving a default route for everything else.

```json
{
  "workspace_dir": ".",
  "agent_max_steps": 8,
  "allow_shell_tools": false,
  "free_only": true,
  "default_route": ["custom-local", "echo"],
  "routes": [
    {
      "name": "coding",
      "keywords": ["code", "bug", "fix", "refactor", "test", "repo"],
      "agents": ["custom-local", "echo"]
    }
  ]
}
```

Each agent can set `context_window`. Before routing, Agent-Hub estimates input
tokens from the messages, adds the requested output budget (`max_tokens` from the
request, then the agent, then `4096`), and skips agents whose context window is
too small. The estimate is intentionally rough, but it keeps obvious over-limit
requests away from smaller local models.

Supported providers:

- `openai-compatible` for your own local server, LocalAI, vLLM, or any local
  gateway exposing `/v1/chat/completions`
- `gemma` as a friendly alias for a local OpenAI-compatible Gemma/Gemma-like agent
- `chatgpt` or `openai` for OpenAI Chat Completions, skipped while `free_only` is true unless marked `free`
- `gemini` or `google` for Gemini `generateContent`, skipped while `free_only` is true unless marked `free`
- `claude` or `anthropic` for Claude Messages API, skipped while `free_only` is true unless marked `free`
- `echo` for local smoke tests without API keys

Cloud agents stay disabled in the example config. To use one later, set the
right `api_key_env`, replace the model placeholder, set `enabled` to `true`, and
either disable `free_only` or explicitly mark that agent as `free` if your usage
is genuinely free.

## Notes

- Streaming is currently bridged as one server-sent event containing the completed
  response, so clients that require true token streaming may still need adapter work.
- Tool schemas are forwarded for OpenAI-compatible requests. Cross-provider tool
  translation is intentionally conservative because vendor tool formats differ.
- Model IDs in the example config are placeholders you should replace with models
  your local servers actually expose.
- Agent file tools are constrained to `workspace_dir`. Shell command execution is
  opt-in because it runs with the permissions of the Agent-Hub process.

API references checked while building this:

- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat/create-chat-completion
- Anthropic Messages: https://docs.anthropic.com/en/api/messages-examples
- Gemini generateContent: https://ai.google.dev/api/generate-content
