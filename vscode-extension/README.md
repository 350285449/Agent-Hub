# Agent Hub Workspace

Run Agent Hub from VS Code. Use the sidebar or `@agenthub` chat to ask
questions, explain code, research, or let a permissioned workspace agent edit
files.

Agent Hub uses the `cloud-agent` route by default. Fresh configs prefer Ollama
Cloud model routes, with hosted API-key providers and local LM Studio/Ollama
models available when you enable them.

## Quick Start

1. Install the extension from the Marketplace or from a `.vsix`.
2. Install Python 3.11 or newer.
3. Open a workspace folder and select the Agent Hub activity bar icon.
4. Type a task in the sidebar `Task` box and choose `Start & Send`.
5. Agent Hub starts the local server when needed and opens the chat with live progress.

For Ollama Cloud, install Ollama and sign in:

   ```sh
   ollama signin
   ```

The packaged extension includes the Agent Hub Python backend. Node.js is only
needed when building the extension from source.

## Ollama Cloud Example

Ollama Cloud models run through Ollama instead of downloading large local model
weights. To try one before using Agent Hub:

```sh
ollama signin
ollama run gpt-oss:120b-cloud
```

In VS Code:

1. Open `Agent Hub: Open Chat`.
2. Open `Settings`.
3. Set `Control agent` to `Cloud`.
4. Set `Cloud route` to `Ollama cloud models first`.
5. Save settings and restart the Agent Hub server.

By default Agent Hub talks to your local Ollama server at
`http://127.0.0.1:11434`, and Ollama handles cloud authentication after
`ollama signin`. If you edit `agent-hub.config.json` to connect directly to
Ollama's hosted API, set `api_key_env` to `OLLAMA_API_KEY` and save that key as
the `Ollama Cloud` key in Agent Hub settings.

If a model name fails, test it with `ollama run <model-name>` first, then update
the matching model in `agent-hub.config.json`. Ollama's supported cloud models
change over time, so use a model available to your Ollama account.

Official docs:

- [Ollama Cloud](https://docs.ollama.com/cloud)
- [Ollama authentication](https://docs.ollama.com/api/authentication)

## Common Commands

- `@agenthub` in VS Code Chat
- `Agent Hub: Open Chat`
- `Agent Hub: Start Server`
- `Agent Hub: Show Status`
- `Agent Hub: Ask Agent`
- `Agent Hub: Run Coding Agent`
- `Agent Hub: Research Web`
- `Agent Hub: Explain Selection`
- `Agent Hub: Explain Current File`

The sidebar shows server status, setup progress, provider health, token usage,
permissions, logs, and shortcuts for common actions. When `agentHub.autoStart`
is enabled, Agent Hub starts the local server before sending a request.

## Provider Modes

- `cloud`: use the configured `cloud-agent` route. This is the default.
- `hybrid`: try cloud providers first, then local fallbacks.
- `local`: use local LM Studio/Ollama routes.

Hosted API-key models are off by default. Enable `API-key models` in the chat
settings menu when you want OpenAI/Codex, Claude, Gemini, Groq, OpenRouter,
Cerebras, Mistral, GitHub Models, Hugging Face, NVIDIA NIM, Cloudflare, or other
configured providers.

To use local models, choose `Local` in settings, then click `Choose Local Model`
to scan LM Studio and Ollama or pull a recommended Ollama model.

## External Agent Setup

Cline, RooCode, OpenCode, and similar OpenAI-compatible clients:

```text
Provider: OpenAI Compatible
Base URL: http://127.0.0.1:8787/v1
API Key: agent-hub-local
Model: agent-hub-coding
```

Claude Code or Anthropic-compatible clients:

```text
ANTHROPIC_BASE_URL=http://127.0.0.1:8787
ANTHROPIC_AUTH_TOKEN=agent-hub-local
ANTHROPIC_MODEL=agent-hub-coding
```

Use the Agent Hub commands `Copy Cline Config`, `Test Cline Connection`, `Copy
Claude Code Config`, and `Test Anthropic Endpoint` to verify the gateway.

## Useful Settings

- `agentHub.serverUrl`: local Agent Hub server URL.
- `agentHub.pythonPath`: Python executable. Use `auto` for normal setups.
- `agentHub.configPath`: workspace config file.
- `agentHub.agentProviderMode`: `cloud`, `hybrid`, or `local`.
- `agentHub.agentMode`: `agent` or `group-agent`.
- `agentHub.approvalMode`: permission mode for file, shell, process, and cloud
  actions.
- `agentHub.autoStart`: start the server automatically when needed.

## Build From Source

From the repository root:

```powershell
.\install-extension.ps1
```

On macOS or Linux:

```sh
sh ./install-extension.sh
```

For a full source setup:

```powershell
.\install.ps1 -WithExtension
```

More docs:

- [Cline setup](https://github.com/350285449/Agent-Hub/blob/main/docs/CLINE.md)
- [Claude Code setup](https://github.com/350285449/Agent-Hub/blob/main/docs/CLAUDE_CODE.md)
- [Permissions](https://github.com/350285449/Agent-Hub/blob/main/docs/PERMISSIONS.md)
- [Troubleshooting](https://github.com/350285449/Agent-Hub/blob/main/docs/TROUBLESHOOTING.md)
- [Publishing](https://github.com/350285449/Agent-Hub/blob/main/vscode-extension/PUBLISHING.md)
