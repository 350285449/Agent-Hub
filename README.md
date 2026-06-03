# Agent-Hub

[![CI passing](https://img.shields.io/github/actions/workflow/status/350285449/Agent-Hub/ci.yml?branch=main&label=CI%20passing)](https://github.com/350285449/Agent-Hub/actions/workflows/ci.yml)
[![tests passing](https://img.shields.io/github/actions/workflow/status/350285449/Agent-Hub/ci.yml?branch=main&label=tests%20passing)](https://github.com/350285449/Agent-Hub/actions/workflows/ci.yml)
[![release validation passing](https://img.shields.io/github/actions/workflow/status/350285449/Agent-Hub/ci.yml?branch=main&label=release%20validation%20passing)](https://github.com/350285449/Agent-Hub/actions/workflows/ci.yml)

Agent-Hub is a local routing layer and lightweight workspace agent for LLM
requests. It accepts JSON, chooses a configured agent/model, can run a small
tool-using agent loop, and fails over to the next agent when a provider is out
of quota, rate limited, overloaded, or cannot handle the context size.

It can also act as a transparent OpenAI endpoint, Anthropic endpoint, Cline
backend, Claude Code backend, OpenRouter-style endpoint, VS Code workspace
agent, and universal provider router. Risky shell, install, file-write,
delete, config, provider, upload, and process actions go through centralized
permission policy.

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
- OpenAI Responses-style endpoint: `POST /v1/responses`
- OpenRouter-style compatibility path: `POST /api/v1/chat/completions`
- Native endpoint: `POST /v1/agent`
- Collaborative team mode: `mode="group-agent"` on `/agent` or `/v1/agent`
- Agent workspace tools: list, read, search, and write files under `workspace_dir`
- Free-only routing and context-window preflight checks before provider calls
- JSON file inbox: `.agent-hub/inbox/*.json`
- Session logs: `.agent-hub/state/sessions/*.json`
- Context diagnostics: `GET /debug/context` and `POST /debug/request`

## Architecture Overview

Agent-Hub is organized around modular backend systems:

- Router: ranks providers by route, task type, health score, context window,
  streaming support, tool support, quota state, and user preference.
- Provider manager: bridges legacy `complete()` adapters with strict
  `chat()` / `stream()` adapters.
- Provider adapters: isolate OpenAI, OpenAI-compatible, Ollama, Anthropic,
  Gemini, local research, and debug echo behavior.
- Streaming system: uses native provider streams when supported and preserves
  compatibility streaming as a fallback.
- Health system: persists latency, reliability, cooldowns, quota state,
  streaming speed, and tool-call reliability between restarts.
- Context engine: estimates tokens, summarizes old messages, preserves recent
  and protected context, and tracks repository memory.
- Workflow engine: runs deterministic Planner -> Worker -> Reviewer workflows.
- Tool layer: exposes MCP-shaped tools, registry, permission checks, execution
  events, OpenAI-compatible tool schemas, and a real provider tool-call loop.
- Repository context: indexes files, important package/config files, imports,
  changed files, and compact evidence for coding/review/debug/refactor tasks.
- Provider evaluation: stores benchmark scores and feeds them back into routing.
- Plugin SDK foundation: discovers local manifest-only provider, tool,
  workflow, router-strategy, and memory/context plugins without executing
  third-party code.
- Dashboard: `/dashboard`, `/dashboard/optimization`, `/v1/status`,
  `/v1/routing-history`, and `/v1/provider-scores` explain model selection,
  adaptive optimization, retry recovery, and tool/workflow activity.

More detail lives in `docs/architecture.md`, `docs/providers.md`,
`docs/workflows.md`, `docs/tools.md`, `docs/mcp.md`, `docs/evaluation.md`,
`docs/install-vsix.md`, `docs/plugins.md`, `docs/deployment.md`, and
`docs/api.md`.

Dedicated setup docs are also available for [Cline](docs/CLINE.md),
[Claude Code](docs/CLAUDE_CODE.md), [Continue](docs/continue.md), and
[Ollama](docs/OLLAMA.md).

## OpenAI-Compatible Usage

Chat completions:

```sh
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"agent-hub-coding","messages":[{"role":"user","content":"Hello"}]}'
```

Streaming:

```sh
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"agent-hub-coding","stream":true,"messages":[{"role":"user","content":"Write a plan"}]}'
```

Streaming responses include `X-Agent-Hub-Stream-Mode: native` when the selected
provider supports true token streaming, otherwise `compatibility`.

## Workflows

Workflow endpoints are available for coding tasks:

- `POST /v1/workflows/code`
- `POST /v1/workflows/review`
- `POST /v1/workflows/debug`
- `POST /v1/workflows/explain`
- `POST /v1/workflows/refactor`
- `POST /v1/auto`

Each workflow is deterministic and explainable: planner, worker, reviewer.
Optional validation, retry-on-review-failure, test command, and patch summary
stages are available through request/config flags.
`/v1/auto` chooses between direct, single-worker, planned, reviewed, and
team-reviewed workflows. Large team-reviewed tasks collect multiple non-editing
worker proposals, judge the best proposal, then run one editing worker with the
selected plan. Adaptive analytics track model win rates, latency, cost, retries,
thumbs up/down feedback, workflow success, and best planner/worker choices per
workflow task in `/dashboard/optimization`.

## Configuration Example

```json
{
  "free_only": true,
  "expose_routing_details": false,
  "adaptive_learning_enabled": true,
  "adaptive_routing_enabled": true,
  "adaptive_workflow_upgrades_enabled": true,
  "approval_mode": "ask",
  "tool_loop_enabled": true,
  "max_tool_iterations": 4,
  "repo_context_enabled": true,
  "routes": [{"name": "coding", "agents": ["ollama-qwen-coder", "custom-local"]}],
  "agents": [
    {
      "name": "custom-local",
      "provider": "openai-compatible",
      "model": "local-model",
      "base_url": "http://127.0.0.1:8000",
      "supports_streaming": true,
      "supports_tools": true,
      "context_window": 32768
    }
  ]
}
```

Migration note: Phase 2-4 config additions are optional. Existing configs keep
working; new defaults enable context-cache metadata and plugin discovery only
for local manifest files. Add `cost_per_million_input` /
`cost_per_million_output` per provider only when you want cost-aware tie
breaking.

Run provider evaluation:

```sh
python -m agent_hub eval --route coding --json
```

Keep real `agent-hub.config.json`, generated `config.example.json` files,
backups, logs, state folders, provider health state, `.vsix` packages, and API
keys out of git. Use `agent-hub.config.example.json` for shareable examples.

## Cline And Continue

Cline:

- Base URL: `http://127.0.0.1:8787/v1`
- API key: `local-agent-hub-token`
- Model: `agent-hub-coding`
- Recommended config: `"approval_mode": "auto"` and
  `"cline_compatibility_mode": true`

Continue:

```json
{
  "title": "Agent-Hub",
  "provider": "openai",
  "model": "agent-hub-coding",
  "apiBase": "http://127.0.0.1:8787/v1",
  "apiKey": "local"
}
```

### Approval Compatibility

Older configs using `approval_mode: "ask"` can return a 403 like
`agent_hub_permission_required` when an IDE client routes workspace context to a
cloud provider. Cline, Continue, Claude Code, and many VS Code extensions cannot
answer Agent-Hub's interactive approval prompt, so Agent-Hub supports
non-interactive client compatibility mode.

With `cline_compatibility_mode: true`, OpenAI-compatible IDE requests can use
trusted cloud providers without an interactive provider prompt. Agent-Hub still
records a permission and security audit event, and it still blocks dangerous
tools, unsafe shell commands, path escapes, unknown external endpoints, and
requests that trigger explicit security rules such as secret detection.

Recommended IDE config:

```json
{
  "approval_mode": "auto",
  "cline_compatibility_mode": true,
  "tool_loop_enabled": true,
  "tool_loop_enabled_for_cline": false,
  "force_compatibility_streaming": true,
  "compatibility_mode": {
    "minimal_tool_schema": true,
    "reduced_repo_context": true,
    "max_context_tokens": null
  }
}
```

For weak, free, or OpenAI-compatible providers, Agent-Hub now validates and
normalizes provider output before returning it to IDE clients. Empty responses,
missing `choices`, malformed tool-call arguments, malformed stream chunks, and
early stream termination are retried or converted into a minimal valid response
instead of surfacing as Cline `Invalid API Response`.

Debug provider payloads with:

```json
{
  "debug_raw_provider_responses": true
}
```

Redacted, truncation-safe traces are written to `.agent-hub/debug/` with
request, provider, stream, token estimate, finish reason, and tool-call details.
Keep this off unless you are diagnosing provider instability.

Internal stability events are written to `.agent-hub/state/events.jsonl`.
Important event names include `provider.selected`, `provider.failed`,
`router.fallback`, `tool.executed`, `stream.started`, `stream.failed`, and
`context.truncated`.

Provider trust levels are:

- `LOCAL`: Ollama/local research/localhost or private OpenAI-compatible
  endpoints. These are always allowed.
- `TRUSTED_CLOUD`: OpenAI, Anthropic, Gemini, Groq, OpenRouter, and
  Ollama Cloud provider types. These are allowed automatically in
  `approval_mode: "auto"` or compatibility mode.
- `UNTRUSTED_EXTERNAL`: unknown external OpenAI-compatible endpoints. These may
  still require explicit approval before workspace content is sent.

Provider routing decisions are written to
`.agent-hub/state/security_audit.jsonl` without prompt content.

Supported provider families include OpenAI, OpenAI-compatible local/cloud
servers, Ollama, OpenRouter, Groq, Anthropic, Gemini, local research, and echo
diagnostics.

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

One-command backend + extension setup on Windows:

```powershell
.\install.ps1 -WithExtension
```

On macOS or Linux:

```sh
sh ./install.sh
sh ./install-extension.sh
```

One-command backend + extension setup on macOS or Linux:

```sh
sh ./install.sh --with-extension
```

The extension installer needs Node.js 20 or newer and a VS Code-compatible CLI.
If `agent-hub.config.json` is missing, the backend now creates a default config
and `.agent-hub` state folders automatically on first start. It also enables
disabled provider entries when their API key environment variables are already
set, and it probes reachable local OpenAI-compatible servers for model IDs.

Then open a second terminal for an interactive Codex-style chat:

```powershell
.\.venv\Scripts\agent-hub.exe chat --allow-shell-tools
```

Or use the VS Code extension command `Agent Hub: Open Chat`.
On first run, the VS Code sidebar checks backend availability, Python version,
config file, provider/API-key state, local Ollama/LM Studio availability, and
then guides you to the primary `Start Server` action.
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

## Free Cloud Provider Presets

Agent-Hub includes editable, disabled-by-default presets for many free-tier or
open cloud providers. Most use the generic `openai-compatible` adapter with
provider metadata for `base_url`, headers, capability scores, and API key env
vars:

- Ollama Cloud, Groq, OpenRouter, Cerebras, Together, Fireworks, DeepInfra,
  Mistral, SambaNova, NVIDIA NIM, GitHub Models, Gemini / Google AI Studio,
  Hugging Face Inference Providers, Cloudflare Workers AI, Hyperbolic,
  Featherless, Replicate gateways, Novita, kluster.ai gateways, Parasail, and
  Anyscale.

Useful commands:

```powershell
python -m agent_hub providers
python -m agent_hub presets
python -m agent_hub presets apply private
python -m agent_hub presets apply fast
python -m agent_hub presets apply cheap
python -m agent_hub presets apply best-coding
python -m agent_hub presets apply local-only
python -m agent_hub add-provider groq --model llama-3.3-70b-versatile --api-key-env GROQ_API_KEY --enabled
python -m agent_hub add-free-presets
python -m agent_hub recommend --route cloud-agent --needs-tools "fix a failing test"
python -m agent_hub health
python -m agent_hub metrics
python -m agent_hub doctor --providers
python -m agent_hub route-test --route cloud-agent "hello"
python -m agent_hub benchmark --route cloud-agent
```

Common env vars include `OLLAMA_API_KEY` when your Ollama setup requires it,
`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `CEREBRAS_API_KEY`,
`TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `DEEPINFRA_API_KEY`,
`MISTRAL_API_KEY`, `SAMBANOVA_API_KEY`, `NVIDIA_API_KEY`, `GITHUB_TOKEN`,
`HUGGINGFACE_API_KEY`, and `CLOUDFLARE_API_TOKEN`.

Free model IDs and quotas move around. The preset system is deliberately just
editable config, so an unavailable model fails over or can be changed without
breaking the hub.
When an API key environment variable is already available, Agent-Hub also adds
matching free provider presets at runtime and inserts them into the cloud/coding
routes. For example, setting `GROQ_API_KEY` is enough for the Groq free presets
to become eligible on the next start; no config edit is required.

To customize routes, model names, token windows, or shell tools, copy and edit
the example config:

```powershell
python -m agent_hub init --with-cloud-examples
python -m agent_hub doctor
python -m agent_hub agents
python -m agent_hub local-models
python -m agent_hub providers
python -m agent_hub presets
python -m agent_hub add-free-presets
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

## Cline And Claude Code

Cline:

```json
{
  "apiProvider": "openai-compatible",
  "openAiBaseUrl": "http://127.0.0.1:8787/v1",
  "openAiApiKey": "agent-hub-local",
  "openAiModelId": "agent-hub-coding",
  "model": "agent-hub-coding"
}
```

Claude Code:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8787
ANTHROPIC_AUTH_TOKEN=agent-hub-local
ANTHROPIC_MODEL=agent-hub-coding
```

The VS Code commands `Agent Hub: Copy Cline Config`,
`Agent Hub: Test Cline Connection`, `Agent Hub: Copy Claude Code Config`, and
`Agent Hub: Test Anthropic Endpoint` provide setup and compatibility checks.

## Context Preservation

`cline_compatibility_mode` is enabled by default. Agent Hub preserves structured
content arrays, `task_progress`, TODO state, tool calls/results, MCP/tool state,
workspace metadata, active/open file metadata, and recent reasoning/action
chains. Token compaction protects those categories and compacts older,
lower-signal content first.

Inspect context with:

```powershell
agent-hub inspect-request .\request.json --api-shape openai-chat
curl http://127.0.0.1:8787/debug/context
```

## Operations

Run:

```powershell
agent-hub doctor
```

The doctor report includes config path, backend version, Python runtime,
install checks, dependency checks, provider config, backend reachability/server
health, bundled backend snapshot status, backend/extension version alignment,
VS Code extension setup, enabled providers, missing API keys, local model
servers, Cline/Claude endpoints, approval mode, safe mode, token optimization
mode, context diagnostics, likely problems, and exact fixes.
Use `agent-hub doctor --json` for issue reports or automation; dependency
checks distinguish the runtime import audit from optional release tooling. The
runtime dependency audit currently reports `packaging` as the only non-stdlib
runtime import because provider transport uses Python stdlib HTTP modules.

Router/provider errors also expose structured categories internally
(`configuration`, `provider`, `rate_limit`, `quota`, `context_limit`,
`validation`, `stream`, and `tool`) so recovery logic can distinguish retryable
provider failures from user-fixable configuration problems.

Further docs:

- [Architecture](docs/architecture.md)
- [Permissions](docs/PERMISSIONS.md)
- [Cline setup](docs/CLINE.md)
- [Claude Code setup](docs/CLAUDE_CODE.md)
- [Token optimization](docs/TOKEN_OPTIMIZATION.md)
- [Privacy and security](docs/PRIVACY_SECURITY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health
```

`/health` includes the initialized config status, enabled agents, provider
health/cooldown data, quota estimates when providers expose them, latency and
reliability metrics, active recommendations, and model aliases exposed to
OpenAI-compatible tools.

Runtime health is persisted in `.agent-hub/state/provider_health.json`.
Agent-Hub stores rolling success/failure counts, timeout counts, average
latency, tool-call completion reliability, cooldown deadlines, observed quota
or request/token counters, and recent failover events. Stale health data expires
safely, but active cooldowns survive restarts so a provider that just exhausted
free-tier quota is not retried immediately after restarting the server.

Diagnostics:

```powershell
python -m agent_hub health --route cloud-agent
python -m agent_hub metrics --route cloud-agent
agent-hub route-diagnose --route cloud-agent --needs-tools "fix a failing test"
python -m agent_hub doctor
agent-hub debug-bundle --output agent-hub-debug-bundle.zip
```

`health` summarizes live availability and current best route candidates.
`metrics` includes persisted latency, streaming-speed estimates, tool-call
success/failure counts, token usage, and recent failover history. `doctor`
combines config readiness with the same provider-health and recommendation
signals. `route-diagnose` shows the selected provider, selected model, skipped
providers, fallback reason, latency, and estimated cost when configured.
`debug-bundle` exports sanitized version info, config, logs, doctor output,
provider status, and release validation results with secret-like values
redacted.

Test proof:

```powershell
python -m pip install -e ".[test,dev,release]"
python -m compileall -q agent_hub scripts
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
Push-Location vscode-extension; npm ci; npm run prepare-backend; Pop-Location
python scripts/validate_release.py
python -m pytest -m "not integration and not stress"
python -m pytest -m packaging
```

Optional slower lanes:

```powershell
python -m pytest -m integration
python -m pytest -m stress
cd vscode-extension
npm run check
npm run check:version
```

Additional visibility endpoints:

- `GET /v1/provider-health`
- `GET /v1/routing/status`
- `GET /v1/routing/last-decision`
- `GET /v1/routing/test-failover`
- `GET /v1/limits`
- `GET /v1/usage`
- `GET /v1/client-sources`
- `GET /v1/events`
- `GET /v1/tools`
- `GET /v1/workflows/status`
- `GET /v1/plugins`
- `GET /v1/enterprise/audit`

When `host` is `0.0.0.0` or another public bind address, these diagnostics
endpoints require `diagnostics_auth_token` or `diagnostics_auth_token_env`.
Localhost keeps the previous no-auth behavior. The generated config reference
is in `docs/config-reference.md`.

Phase 6 adds platform hardening without enabling risky behavior by default:
plugin manifests can be trusted by registry hash/signature or explicit
allowlist, plugin execution remains disabled behind a deny-by-default sandbox
interface, enterprise permission decisions are audited to local state, and
`python -m agent_hub migrate-config` can detect and write small config key
migrations.

Deployment templates are included as `Dockerfile`, `docker-compose.yml`,
`.env.example`, and `examples/agent-hub.production.json`. Community config
starting points live in `examples/config-*.json`.

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

`vscode-extension/backend` is generated during packaging and intentionally
gitignored. Run `cd vscode-extension && npm run prepare-backend` to regenerate
it without packaging a VSIX. The equivalent root-level validation flow is:

```sh
python scripts/generate_backend_snapshot.py
python scripts/validate_backend_drift.py
cd vscode-extension && npm run prepare-backend
```

After installing, reload VS Code, open any workspace, and use:

- `Agent Hub: Open Chat`
- `Agent Hub: Start Server`
- `Agent Hub: Show Status`
- `Agent Hub: Ask Agent`
- `Agent Hub: Run Coding Agent`
- `Agent Hub: Research Web`
- `Agent Hub: Explain Selection`
- `Agent Hub: Explain Current File`

The extension uses the same local server as the CLI. Packaged VSIX builds
include the Agent Hub Python backend and start it from the opened workspace with
an extension-managed per-workspace config stored in VS Code global storage. This
keeps generated config and backup files out of git by default. Set
`agentHub.configPath` to an absolute path or `./agent-hub.config.json` only when
you intentionally want a project-local config. Settings are available under
`Agent Hub`, including `agentHub.serverUrl`, `agentHub.pythonPath` (`auto` tries
common Python 3.11+ launchers), `agentHub.configPath`,
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

Use any non-empty API key value for local clients that require one. Useful model
IDs are:

- `agent-hub`: automatic free cloud route
- `agent-hub-coding`: coding/tool-capable route
- `agent-hub-local`: local-only route
- `agent-hub-research`: local research route
- any route name, agent name, or enabled provider model returned by `/v1/models`

If a client selects a specific agent/model, Agent-Hub tries that first and then
falls back to the rest of the route candidates when the preferred model is
temporarily unavailable.

Anthropic-compatible clients can call:

```text
http://127.0.0.1:8787/v1/messages
```

OpenAI Responses-compatible clients can call:

```text
http://127.0.0.1:8787/v1/responses
```

OpenRouter-style clients can also point at:

```text
http://127.0.0.1:8787/api/v1
```

## Cline And Claude Code-Style Setup

Start Agent-Hub first:

```powershell
python -m agent_hub serve --watch-inbox
```

Claude Code / Anthropic-compatible clients:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8787
ANTHROPIC_AUTH_TOKEN=local-agent-hub-token
Model: agent-hub-coding
```

For Cline or any OpenAI-compatible coding extension:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:8787/v1
API Key: local-agent-hub-token
Model: agent-hub-coding
Streaming: on or off
```

`agent-hub-coding` is a route alias, not a single provider model. It ranks the
enabled free models for coding/tool use, preserves OpenAI `tool_calls`, and
falls back across eligible providers when a model hits quota, rate limits,
context limits, token exhaustion, or overload.

For Claude Code-style tools that can use an OpenAI-compatible/custom model
endpoint, use the same settings:

```text
Base URL: http://127.0.0.1:8787/v1
Model: agent-hub-coding
API key: local-agent-hub-token
```

For tools that use the Anthropic Messages API shape instead, point their
Anthropic-compatible base URL at the local server and keep the same model alias:

```text
Base URL: http://127.0.0.1:8787
Messages endpoint: /v1/messages
Model: agent-hub-coding
API key: local-agent-hub-token
```

For tools that use the OpenAI Responses API shape:

```text
Base URL: http://127.0.0.1:8787/v1
Responses endpoint: /responses
Model: agent-hub-coding
API key: local-agent-hub-token
```

Agent-Hub accepts OpenAI Chat Completions, OpenAI Responses, Anthropic Messages,
and native `/v1/agent` requests. It forwards or translates tool definitions
where possible and returns OpenAI-compatible `tool_calls` when the routed model
chooses a tool.

During agent workflows, every model turn keeps the same conversation, session
history, tool results, and workspace state. If a provider is rate-limited,
overloaded, out of free-tier quota, near an observed token/request limit, too
slow, or repeatedly unreliable, future turns are routed to healthier candidates.
Failures during one model step are retried with the same step request, so the
completed local work and accumulated tool trace are preserved.

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
Quota, rate-limit, exhausted free-tier, and token-limit errors are marked as
temporary provider/model unavailability and cooled down before the next retry.
The client keeps the same public model alias and session history unless routing
details are explicitly exposed.
For OpenAI-compatible clients, route aliases such as `agent-hub-coding` keep the
same public `model` value in every response even when the internal provider
changes during failover.

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
- `apply_patch`, preferred for coordinated multi-file edits
- `run_command`, disabled unless `allow_shell_tools` is `true`

The agent no longer treats the first successful file edit as task completion by
default. It keeps looping after `write_file`, `replace_in_file`, or
`apply_patch` until the model returns a final answer or the step limit is
reached. Set `fast_write_finalize` to `true` or pass
`--fast-write-finalize` to keep the older one-edit-and-finish behavior.

`apply_patch` accepts either a unified diff or structured changes and validates
every target path before writing anything. If any path or replacement fails
validation, nothing is applied. In `approval_mode: "ask"`, patch requests return
one grouped approval payload with affected files, summary, patch preview,
planned commands, and validation plan.

After edits, Agent-Hub can validate changed code. `validation_mode: "basic"`
runs Python syntax checks for changed `.py` files and the default pytest lane
(`python -m pytest -m "not integration and not stress"`) when tests exist.
`validation_mode: "strict"` also runs configured
validation commands. Disable with `validation_mode: "off"` or
`--no-auto-validate`.

For a Codex-like coding workflow, run a local OpenAI-compatible model through
Ollama or LM Studio, then use `Agent Hub: Run Coding Agent` in VS Code or:

```powershell
python -m agent_hub agent --allow-shell-tools "inspect the repo and fix the failing tests"
python -m agent_hub agent --validation-mode strict --validation-command "python -m pytest -m \"not integration and not stress\"" "update implementation, tests, and docs"
```

To ask before every shell command in CLI agent modes, add
`--confirm-shell-tools` or set `"shell_command_policy": "ask"` in config. The
non-interactive HTTP server reports a clear tool error when a command needs
permission but no prompt channel is available.

For an ongoing chat session that keeps conversation history, use:

```powershell
python -m agent_hub chat --allow-shell-tools
```

## Group-Agent Mode

`group-agent` coordinates several routed models around the same safe workspace
tools:

- Planner proposes one or more implementation plans.
- Researcher gathers repo context with read/search/list tools.
- Coder edits through `write_file` or `replace_in_file`.
- Reviewer checks the trace for bugs, scope drift, and missing verification.
- Fixer applies blocking review fixes when needed.
- Finalizer summarizes changed files, verification, failover, and risks.

Run it from the CLI:

```powershell
python -m agent_hub group-agent --allow-shell-tools --plan-candidates 3 "fix the failing tests"
```

Or through HTTP:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/v1/agent `
  -Method Post `
  -ContentType "application/json" `
  -Body (@{
    mode = "group-agent"
    route = "cloud-agent"
    task = "inspect the repo and make the requested coding change"
    group_agent = @{ plan_candidates = 3 }
  } | ConvertTo-Json -Depth 5)
```

Plan voting uses a judge-style heuristic by default: it rewards requested file
paths, scoped edits, inspection, and verification, and penalizes destructive
rewrites, hallucinated paths, outside-root paths, and accidental duplicate-copy
edits. You can pin roles with `group_roles` in config, or let Agent-Hub rank
models using `coding_score`, `reasoning_score`, `speed_score`, context window,
tool support, and priority.

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
`apply_patch`, `list_files`, and, when enabled, `run_command`; compatible models can call those
tools directly, and write/replace tools update files on disk as soon as the tool
step runs. The `echo` provider remains diagnostic only and cannot edit files.

```json
{
  "workspace_dir": ".",
  "agent_max_steps": 8,
  "allow_shell_tools": true,
  "shell_command_policy": "allow",
  "approval_mode": "auto",
  "fast_write_finalize": false,
  "validation_mode": "basic",
  "validation_commands": [],
  "auto_validate_after_edits": true,
  "free_only": true,
  "auto_enable_available_providers": true,
  "auto_detect_local_models": true,
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
request, then an agent-configured value when present), and skips agents whose
context window is too small. When no output budget is configured, routing stays
in auto mode instead of applying a hidden default output cap.

Provider/model failover is silent by default. If a request does not fit the
primary control model, or a provider reports context/token pressure, Agent-Hub
tries the next configured fallback while returning the same public `model` alias
to the client. Set `expose_routing_details` to `true` only when you want
developer debug output showing the internal agent, model, and failover trace.

For model proposal without making a provider call, use:

```powershell
python -m agent_hub recommend --route cloud-agent --prefer coding --needs-tools "edit the repo"
```

or call `POST /v1/recommend-model` with `task`, `route`, `limit`, and optional
`prefer` (`coding`, `reasoning`, or `speed`). Recommendations rank enabled,
eligible agents using free/paid status, coding/reasoning/speed scores, context
window, tool support, route order, known token cost, and recent provider health.
The router uses the same scoring signals during live routing, with an extra
bonus for tool/function-calling models when the request contains tools or is
running in agent mode.

Supported providers:

- `openai-compatible` for your own local server, LocalAI, vLLM, or any local
  gateway exposing `/v1/chat/completions`
- `local-research` for free local extractive web research with citations and
  search results, using no cloud LLM or paid API
- `gemma` as a friendly alias for a local OpenAI-compatible Gemma/Gemma-like agent
- `ollama-cloud`, `groq`, `openrouter`, `cerebras`, `together`, `fireworks`,
  `deepinfra`, `mistral`, `sambanova`, `nvidia-nim`, `github-models`,
  `google-ai-studio`, `huggingface`, `cloudflare-workers-ai`, `hyperbolic`,
  `featherless`, `novita`, `parasail`, and `anyscale` are represented as
  OpenAI-compatible provider types with defaults in the provider registry
- `replicate` and `kluster` are supported as provider types for future or custom
  OpenAI-compatible gateways; their native APIs are not treated as chat
  completion APIs unless you set a compatible `base_url`
- `codex`, `claude`, `gemini`, and `chatgpt` are hosted control providers using
  `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GEMINI_API_KEY`; fresh configs keep
  editable entries for them, and Agent-Hub auto-enables them at runtime when the
  matching API key environment variable is present
- `openai`, `google`, and `anthropic` API providers can be added or changed with
  `agent-hub enable-provider`; broad OpenAI-compatible providers can be added
  with `agent-hub add-provider`
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
- Router failover detects common auth, quota, rate-limit, context, and 5xx
  failures, applies rolling cooldowns, tracks success rates and latency, and
  ranks eligible providers by priority plus recent health.
- Missing configs are initialized automatically; `doctor` reports providers
  enabled from environment variables and local model IDs selected from probes.
- Tool schemas are forwarded for OpenAI-compatible requests. Anthropic/Gemini
  routing translates OpenAI-style function tools where possible, and OpenAI
  responses preserve routed `tool_calls` for external agent clients.
- Local model IDs in the example config are placeholders you should replace with
  models your local servers actually expose.
- Agent file tools are constrained to `workspace_dir`. Shell command execution
  runs with the permissions of the Agent-Hub process, so disable
  `allow_shell_tools` when you want a read/write-only workspace agent.

Local model references:

- Ollama qwen2.5-coder: https://ollama.com/library/qwen2.5-coder
- Ollama Gemma 3: https://ollama.com/library/gemma3
- Ollama Llama 3.2: https://ollama.com/library/llama3.2
