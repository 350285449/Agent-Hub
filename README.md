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
python -m agent_hub local-models
```

Cloud providers are opt-in. To enable one, choose a model ID and API key
environment variable:

```powershell
python -m agent_hub enable-provider openai --model your-openai-model
python -m agent_hub enable-provider claude --model your-claude-model
python -m agent_hub enable-provider gemini --model your-gemini-model
```

That sets `free_only` to `false`, enables the selected provider, and adds it to
the `cloud-agent` route. In VS Code, set `agentHub.agentProviderMode` to
`hybrid` to try local models first, or `cloud` to try enabled cloud providers
first. Leave it as `local` for fully local/free behavior.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health
```

## VS Code Extension

The repo includes a VS Code extension in `vscode-extension/` so you can use
Agent-Hub from the Command Palette and editor context menu.

Run it directly from the GitHub clone:

```powershell
python -m agent_hub doctor
code vscode-extension
```

In the `vscode-extension` window, press `F5` to launch an Extension Development
Host. In that new VS Code window, open this repository folder and use:

- `Agent Hub: Start Server`
- `Agent Hub: Show Status`
- `Agent Hub: Ask Agent`
- `Agent Hub: Run Local Coding Agent`
- `Agent Hub: Research Web`
- `Agent Hub: Explain Selection`
- `Agent Hub: Explain Current File`

The extension uses the same local server and config as the CLI. By default it
starts `python -m agent_hub --config agent-hub.config.json serve --watch-inbox`
from the opened workspace. Settings are available under `Agent Hub`, including
`agentHub.serverUrl`, `agentHub.pythonPath`, `agentHub.configPath`,
`agentHub.route`, `agentHub.codingAgentRoute`, `agentHub.researchRoute`,
`agentHub.agentMaxSteps`, `agentHub.allowShellTools`, `agentHub.maxTokens`, and
`agentHub.autoStart`.

See [vscode-extension/README.md](vscode-extension/README.md) for the full
GitHub setup guide.

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
- `replace_in_file`
- `run_command`, disabled unless `allow_shell_tools` is `true`

For a Codex-like local coding workflow, run a local OpenAI-compatible model at
the configured `custom-local.base_url`, then use `Agent Hub: Run Local Coding
Agent` in VS Code or:

```powershell
python -m agent_hub agent --allow-shell-tools "inspect the repo and fix the failing tests"
```

The dedicated `local-agent` route uses only free local model endpoints, so
coding-agent requests do not fall back to the `echo` smoke-test provider. The
CLI agent command also forces `free_only=true` unless you explicitly pass
`--allow-cloud`.

Agent-Hub includes free local model presets for:

- Ollama at `http://127.0.0.1:11434`
- LM Studio at `http://127.0.0.1:1234`
- LocalAI at `http://127.0.0.1:8080`
- vLLM or another custom local server at `http://127.0.0.1:8000`

Run `python -m agent_hub local-models` to see which local servers are online and
which model IDs they expose. Change the model names in `agent-hub.config.json`
or with environment variables such as `AGENT_HUB_OLLAMA_CODER_MODEL`,
`AGENT_HUB_LM_STUDIO_MODEL`, `AGENT_HUB_LOCALAI_MODEL`, and
`AGENT_HUB_VLLM_MODEL`.

Example Ollama setup:

```powershell
ollama pull qwen2.5-coder:7b
ollama serve
python -m agent_hub local-models
python -m agent_hub agent --allow-shell-tools "inspect this repo"
```

For LM Studio, start its local server and load a model, then set
`AGENT_HUB_LM_STUDIO_MODEL` to the model ID shown by `agent-hub local-models`.

## Config

Routes are ordered lists of agents. Keyword routes can steer coding work to coder
models while the built-in research route can run a free local research pass:
search public web results, fetch pages from this machine, extract useful
snippets, and return citations without a paid API key.

```json
{
  "workspace_dir": ".",
  "agent_max_steps": 8,
  "allow_shell_tools": false,
  "free_only": true,
  "expose_routing_details": false,
  "default_route": ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai", "echo"],
  "routes": [
    {
      "name": "coding",
      "keywords": ["code", "bug", "fix", "refactor", "test", "repo"],
      "agents": ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai", "echo"]
    },
    {
      "name": "local-agent",
      "keywords": ["agent", "workspace", "edit", "implement"],
      "agents": ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai"]
    },
    {
      "name": "hybrid-agent",
      "keywords": [],
      "agents": ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai", "chatgpt", "claude", "gemini"]
    },
    {
      "name": "cloud-agent",
      "keywords": [],
      "agents": ["chatgpt", "claude", "gemini", "ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai"]
    },
    {
      "name": "research",
      "keywords": ["research", "search", "latest", "sources", "web", "news"],
      "agents": ["local-research", "custom-local", "echo"]
    }
  ]
}
```

Each agent can set `context_window`. Before routing, Agent-Hub estimates input
tokens from the messages, adds the requested output budget (`max_tokens` from the
request, then the agent, then `4096`), and skips agents whose context window is
too small. The estimate is intentionally rough, but it keeps obvious over-limit
requests away from smaller local models.

Provider/model failover is silent by default. If a request does not fit one
local model, or a provider reports context/token pressure, Agent-Hub tries the
next configured free local model while returning the same public `model` alias to
the client. Set `expose_routing_details` to `true` only when you want developer
debug output showing the internal agent, model, and failover trace.

Supported providers:

- `openai-compatible` for your own local server, LocalAI, vLLM, or any local
  gateway exposing `/v1/chat/completions`
- `local-research` for free local extractive web research with citations and
  search results, using no cloud LLM or paid API
- `gemma` as a friendly alias for a local OpenAI-compatible Gemma/Gemma-like agent
- `chatgpt` or `openai` for OpenAI Chat Completions, skipped while `free_only` is true unless marked `free`
- `gemini` or `google` for Gemini `generateContent`, skipped while `free_only` is true unless marked `free`
- `claude` or `anthropic` for Claude Messages API, skipped while `free_only` is true unless marked `free`
- `echo` for local smoke tests without API keys

Cloud agents stay disabled in the example config. To use one later, set the
right `api_key_env`, replace the model placeholder, set `enabled` to `true`, and
either disable `free_only` or explicitly mark that agent as `free` if your usage
is genuinely free.

For cited research answers in VS Code, run `Agent Hub: Research Web`. The
`local-research` agent is enabled by default, marked free, and returns top-level
`citations` and `search_results`. It is extractive rather than a cloud LLM: the
summary is built from fetched source text on your machine.

Current web research still uses your machine's normal internet connection to
search and fetch public pages. It does not use a cloud AI model, paid search API,
or hosted agent service.

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
