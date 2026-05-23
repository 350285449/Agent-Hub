# Agent Hub

Run Agent-Hub from VS Code and send coding, research, and explanation requests
through Ollama cloud models by default, with hosted API-key models and explicit
local control as configurable options.

## Quick Start

1. Install Node.js 20 or newer and Python 3.11 or newer.
2. Install/start Ollama for Ollama cloud routing, or set a hosted provider API key.
3. Package and install the extension from the repository root:

   ```powershell
   .\install-extension.ps1
   ```

   On macOS or Linux:

   ```sh
   sh ./install-extension.sh
   ```

4. Reload VS Code.
5. Open any workspace and run an Agent Hub command from the Command Palette.

Packaged builds include the Agent Hub Python backend. A source checkout can
still use `.\install.ps1` if you want a local editable `.venv`.

For a single setup command from a source checkout:

```powershell
.\install.ps1 -WithExtension
```

On macOS or Linux:

```sh
sh ./install.sh --with-extension
```

## Commands

- `@agenthub` in the VS Code Chat view
- `Agent Hub: Open Chat`
- `Agent Hub: Start Server`
- `Agent Hub: Show Status`
- `Agent Hub: Ask Agent`
- `Agent Hub: Run Coding Agent`
- `Agent Hub: Research Web`
- `Agent Hub: Explain Selection`
- `Agent Hub: Explain Current File`

When `agentHub.autoStart` is enabled, the extension starts the local server for
you before sending a request.

Workspace-agent turns can modify files while the live run is in progress. Agent
Hub exposes file tools to compatible models, applies `write_file` and
`replace_in_file` directly to the workspace, and streams a progress event when a
file edit lands on disk.

The chat header includes a `Settings` menu for provider mode, standard versus
group-agent mode, planner candidate count, API-key and free-cloud model
enablement, Cloud route priority, model names, router flags, server settings,
local model selection, API keys, and server actions.

## Common Settings

- `agentHub.serverUrl`: local Agent-Hub server URL. Default:
  `http://127.0.0.1:8787`
- `agentHub.pythonPath`: Python executable or launcher. Default: `auto`
- `agentHub.configPath`: config file path. Default: `agent-hub.config.json`
- `agentHub.agentProviderMode`: `local`, `hybrid`, or `cloud`. Default: `cloud`
- `agentHub.agentMode`: `agent` or `group-agent`. Default: `agent`
- `agentHub.groupPlanCandidates`: planner candidates for group-agent mode.
  Default: `1`
- `agentHub.autoStart`: automatically start the server when needed. Default:
  `true`

## Control Agent Mode

Agent Hub uses cloud control by default. The generated `cloud-agent` route now
tries Ollama cloud model IDs first, so it does not download or run large local
weights:

- `kimi-k2.6:cloud`
- `glm-5.1:cloud`
- `qwen3.5:cloud`
- `nemotron-3-super:cloud`
- `gemma4:31b-cloud`

Hosted API-key providers are disabled by default. Open the chat `Settings` menu
and enable `API-key models` when you want these providers available; set `Cloud
route` to `API-key models first` when you also want them to lead the route:

- `codex` and `chatgpt` -> OpenAI via `OPENAI_API_KEY`
- `claude` -> Anthropic via `ANTHROPIC_API_KEY`
- `gemini` -> Google Gemini via `GEMINI_API_KEY`

Use the model-name fields in `Settings` to change the hosted model IDs, then
save API keys in VS Code secret storage. Restart Agent Hub from that menu after
saving settings or keys so the Python server receives the updated config and
environment variables.

The same menu can enable the newer free-cloud preset agents for Groq,
OpenRouter, Cerebras, Mistral, GitHub Models, Hugging Face, NVIDIA NIM, and
Cloudflare Workers AI. Additional provider keys, including Together, Fireworks,
DeepInfra, SambaNova, Hyperbolic, Featherless, Novita, Parasail, and Anyscale,
can be saved in the API Keys panel for configs that use those providers.

Choose Local in the chat panel, or set `agentHub.agentProviderMode` to `local`,
to use direct local model routes. Use the chat panel's `Choose Local Model`
button to scan LM Studio and Ollama, pick an installed local model, or pull a
recommended Ollama model. When no local models are found, the install menu shows
each model's approximate storage size before pulling it. `hybrid` follows the
same Cloud route priority and then falls back through the remaining providers.

Ollama's Launch page shows integrations such as Claude Code, Codex App, Hermes
Agent, and OpenClaw. They are not model IDs; Agent Hub uses the models reported
by `ollama list`, then those integrations can be launched separately with
`ollama launch <integration> --model <model>`.

To see available local model servers, run:

```powershell
python -m agent_hub local-models
```

After changing provider settings, restart the Agent-Hub server.

## External Coding Agents

Claude Code / Anthropic-compatible clients:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8787
ANTHROPIC_AUTH_TOKEN=local-agent-hub-token
Model: agent-hub-coding
```

Cline / RooCode / OpenCode:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:8787/v1
API Key: local-agent-hub-token
Model: agent-hub-coding
```

## Development

To test the extension from source:

1. Open `vscode-extension` in VS Code.
2. Press `F5` to launch an Extension Development Host.
3. In the new VS Code window, open the Agent-Hub repository folder.

To package and install from inside `vscode-extension`:

```powershell
cd vscode-extension
npm run install-extension
```

For the Marketplace release checklist, see
[PUBLISHING.md](https://github.com/350285449/Agent-Hub/blob/main/vscode-extension/PUBLISHING.md).
