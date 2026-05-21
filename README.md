# Agent-Hub

Agent-Hub is a local routing layer and lightweight workspace agent for LLM
requests. It accepts JSON, chooses a configured agent/model, can run a small
tool-using agent loop, and fails over to the next agent when a provider is out
of quota, rate limited, overloaded, or cannot handle the context size.

It uses the `cloud-agent` route by default for the model calls that plan and
assign workspace actions. Fresh configs put Ollama cloud model IDs first on that
route, so no heavy local model is run unless you explicitly choose Local control.
Hosted API-key providers remain available as configurable fallbacks. It does not
automate bypassing free-tier limits, scraping web UIs, or downloading
proprietary vendor models.

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

Fresh clone on Windows:

```powershell
.\install.ps1
.\start-agent-hub.ps1
```

Install the VS Code extension from this checkout:

```powershell
.\install-extension.ps1
```

On macOS or Linux:

```sh
sh ./install-extension.sh
```

The extension installer needs Node.js 20 or newer and a VS Code-compatible CLI.

Then open a second terminal for an interactive Codex-style chat:

```powershell
.\.venv\Scripts\agent-hub.exe chat --allow-shell-tools
```

Or use the VS Code extension command `Agent Hub: Open Chat`.
Cloud control starts with Ollama cloud model IDs in fresh VS Code configs. Those
models run through Ollama Cloud, not on your local CPU/GPU. To put hosted API-key
models first, open the chat `Settings` menu, set `Cloud route` to `API-key
models first`, save provider keys, and restart Agent Hub.

Manual start without installing into a virtual environment:

```powershell
python -m agent_hub serve --watch-inbox
```

That starts with the built-in config. You can tune hosted cloud control models
with environment variables:

```powershell
$env:AGENT_HUB_CODEX_MODEL = "gpt-4o-mini"
$env:AGENT_HUB_CLAUDE_MODEL = "claude-3-5-haiku-latest"
$env:AGENT_HUB_GEMINI_MODEL = "gemini-2.0-flash"
```

You can also point it at your own local server without a config file:

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

The local control route can use Ollama model IDs. Pull the default with:

```powershell
ollama pull qwen2.5-coder:7b
```

In VS Code, `agentHub.agentProviderMode` defaults to `cloud`, which uses the
configured `cloud-agent` route. Fresh configs use Ollama cloud model IDs first.
Open the chat `Settings` menu to switch Cloud route priority to API-key models,
change hosted model IDs, or choose Local for direct local-only control.
`hybrid` follows the same Cloud route priority and then falls through remaining
providers.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health
```

## VS Code Extension

The repo includes a VS Code extension in `vscode-extension/` so you can use
Agent-Hub from the Command Palette and editor context menu.

Install it from the GitHub clone:

```powershell
.\install-extension.ps1
```

The installer packages the extension, bundles the Python backend, finds the
`code`/`code-insiders`/`codium` CLI, installs the VSIX with `--force`, and warns
if Python 3.11+ is missing. It needs Node.js 20 or newer to build the VSIX.
After installing, reload VS Code, open any workspace, and use:

- `Agent Hub: Open Chat`
- `Agent Hub: Start Server`
- `Agent Hub: Show Status`
- `Agent Hub: Ask Agent`
- `Agent Hub: Run Coding Agent`
- `Agent Hub: Research Web`
- `Agent Hub: Explain Selection`
- `Agent Hub: Explain Current File`

The extension uses the same local server and config as the CLI. Packaged VSIX
builds include the Agent Hub Python backend and start
`python -m agent_hub --config agent-hub.config.json serve --watch-inbox` from
the opened workspace. Settings are available under `Agent Hub`, including
`agentHub.serverUrl`, `agentHub.pythonPath` (`auto` tries common Python 3.11+
launchers), `agentHub.configPath`,
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
`free_only` is enabled, Agent-Hub only uses agents marked `free`, `echo`, and
local/private `openai-compatible` agents. The default Claude, Gemini, and
ChatGPT entries are local `openai-compatible` aliases. If a local endpoint is
offline, a model is missing, or the request does not fit that model's configured
token window, Agent-Hub records that event and retries the next agent.

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
Native agent requests can set `"stream": true` to receive server-sent progress
events for model steps and tool execution while the final answer is still being
prepared.

Available tools:

- `list_files`
- `read_file`
- `search_files`
- `write_file`
- `replace_in_file`
- `run_command`, disabled unless `allow_shell_tools` is `true`

For a Codex-like coding workflow, run a local OpenAI-compatible model through
Ollama or LM Studio, then use `Agent Hub: Run Coding Agent` in VS Code or:

```powershell
python -m agent_hub agent --allow-shell-tools "inspect the repo and fix the failing tests"
```

For an ongoing chat session that keeps conversation history, use:

```powershell
python -m agent_hub chat --allow-shell-tools
```

The dedicated `local-agent` route uses only direct free local model endpoints.
The default `cloud-agent` route uses Ollama cloud model IDs and keeps hosted
providers such as OpenAI, Anthropic, and Gemini disabled until you opt in. Enable
API-key models in the VS Code chat `Settings` menu, or run `agent-hub
enable-provider`, to add hosted providers back to that route. Local LM
Studio/Ollama models are only on the Local route unless you add them yourself.
The CLI agent command also forces `free_only=true` unless you explicitly pass
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

Example local-control Ollama setup:

```powershell
ollama pull qwen2.5-coder:7b
ollama serve
python -m agent_hub local-models
python -m agent_hub agent --route local-agent --allow-shell-tools "inspect this repo"
```

The Ollama desktop app's Launch page lists integrations such as Claude Code,
Codex App, Hermes Agent, and OpenClaw. Those entries are launch targets, not
model IDs. Agent-Hub talks to the Ollama model server, so it uses model IDs from
`ollama list` such as `qwen2.5-coder:7b`; you can pass the same model to a
Launch integration separately:

```powershell
ollama launch <integration> --model qwen2.5-coder:7b
```

For LM Studio, start its local server and load a model. The VS Code extension
detects the loaded model automatically when it creates or repairs
`agent-hub.config.json`; for CLI-only use, set `AGENT_HUB_LM_STUDIO_MODEL` to
the model ID shown by `agent-hub local-models`.

## Config

Routes are ordered lists of agents. Keyword routes can steer coding work to coder
models while the built-in research route can run a free local research pass:
search public web results, fetch pages from this machine, extract useful
snippets, and return citations without a paid API key.

Workspace-agent requests can edit files live. The backend exposes native tool
schemas for `read_file`, `write_file`, `replace_in_file`, `search_files`,
`list_files`, and, when enabled, `run_command`; compatible models can call those
tools directly, and write/replace tools update files on disk as soon as the tool
step runs. The `echo` provider remains diagnostic only and cannot edit files.

```json
{
  "workspace_dir": ".",
  "agent_max_steps": 8,
  "allow_shell_tools": true,
  "free_only": true,
  "expose_routing_details": false,
  "cloud_control_selection": {"route_mode": "ollama-cloud", "api_key_models_enabled": false},
  "default_route": ["ollama-kimi-cloud", "ollama-glm-cloud", "ollama-qwen-cloud", "ollama-nemotron-cloud", "ollama-gemma-cloud", "echo"],
  "routes": [
    {
      "name": "coding",
      "keywords": ["code", "bug", "fix", "refactor", "test", "repo"],
      "agents": ["ollama-kimi-cloud", "ollama-glm-cloud", "ollama-qwen-cloud", "ollama-nemotron-cloud", "ollama-gemma-cloud", "echo"]
    },
    {
      "name": "local-agent",
      "keywords": ["agent", "workspace", "edit", "implement"],
      "agents": ["ollama-qwen-coder", "ollama-qwen3", "lm-studio", "vllm", "custom-local", "localai"]
    },
    {
      "name": "hybrid-agent",
      "keywords": [],
      "agents": ["ollama-kimi-cloud", "ollama-glm-cloud", "ollama-qwen-cloud", "ollama-nemotron-cloud", "ollama-gemma-cloud", "echo"]
    },
    {
      "name": "cloud-agent",
      "keywords": [],
      "agents": ["ollama-kimi-cloud", "ollama-glm-cloud", "ollama-qwen-cloud", "ollama-nemotron-cloud", "ollama-gemma-cloud", "echo"]
    },
    {
      "name": "research",
      "keywords": ["research", "search", "latest", "sources", "web", "news"],
      "agents": ["local-research", "ollama-kimi-cloud", "ollama-glm-cloud", "ollama-qwen-cloud", "ollama-nemotron-cloud", "ollama-gemma-cloud", "echo"]
    }
  ]
}
```

Each agent can set `context_window`. Before routing, Agent-Hub estimates input
tokens from the messages, adds the requested output budget (`max_tokens` from the
request, then the agent, then `4096`), and skips agents whose context window is
too small. The estimate is intentionally rough, but it keeps obvious over-limit
requests away from smaller local models.

Provider/model failover is silent by default. If a request does not fit the
primary control model, or a provider reports context/token pressure, Agent-Hub
tries the next configured fallback while returning the same public `model` alias
to the client. Set `expose_routing_details` to `true` only when you want
developer debug output showing the internal agent, model, and failover trace.

Supported providers:

- `openai-compatible` for your own local server, LocalAI, vLLM, or any local
  gateway exposing `/v1/chat/completions`
- `local-research` for free local extractive web research with citations and
  search results, using no cloud LLM or paid API
- `gemma` as a friendly alias for a local OpenAI-compatible Gemma/Gemma-like agent
- `ollama-kimi-cloud`, `ollama-glm-cloud`, `ollama-qwen-cloud`,
  `ollama-nemotron-cloud`, and `ollama-gemma-cloud` use Ollama cloud model IDs
  through the Ollama server API without downloading or running local weights
- `codex`, `claude`, `gemini`, and `chatgpt` are hosted control providers using
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`; fresh configs keep
  them disabled until you turn on API-key models in the VS Code Settings menu or
  run `agent-hub enable-provider`
- `openai`, `google`, and `anthropic` API providers can be added or changed
  with `agent-hub enable-provider`; paid providers are skipped while
  `free_only` is true unless marked `free`
- `echo` for local smoke tests without API keys

To avoid hosted model calls entirely, keep `Enable API-key models` off in the VS
Code Settings menu, use the `local-agent` route, or set the VS Code control mode
to Local. To use hosted providers, enable API-key models and optionally set the
`Cloud route` option to `API-key models first`, or run `agent-hub
enable-provider`, then restart the Agent-Hub server.

For cited research answers in VS Code, run `Agent Hub: Research Web`. The
`local-research` agent is enabled by default, marked free, and returns top-level
`citations` and `search_results`. It is extractive rather than a cloud LLM: the
summary is built from fetched source text on your machine.

Current web research still uses your machine's normal internet connection to
search and fetch public pages. It does not use a cloud AI model, paid search API,
or hosted agent service.

## Notes

- Native agent streaming emits live step/tool progress and a final response over
  server-sent events. Provider token streaming is still normalized into completed
  provider turns inside the agent loop.
- Tool schemas are forwarded for OpenAI-compatible requests. Cross-provider tool
  translation is intentionally conservative because vendor tool formats differ.
- Local model IDs in the example config are placeholders you should replace with
  models your local servers actually expose.
- Agent file tools are constrained to `workspace_dir`. Shell command execution
  runs with the permissions of the Agent-Hub process, so disable
  `allow_shell_tools` when you want a read/write-only workspace agent.

Local model references:

- Ollama qwen2.5-coder: https://ollama.com/library/qwen2.5-coder
- Ollama Gemma 3: https://ollama.com/library/gemma3
- Ollama Llama 3.2: https://ollama.com/library/llama3.2
