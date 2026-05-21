# Agent Hub

Run Agent-Hub from VS Code and send coding, research, and explanation requests
through Codex/Claude-style local routing backed by LM Studio or Ollama.

## Quick Start

1. Install Python 3.11 or newer.
2. Start LM Studio with a loaded model, or install Ollama.
3. Package and install the extension:

   ```powershell
   cd vscode-extension
   npm run package
   $env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd --install-extension .\agent-hub-vscode-0.4.10.vsix --force
   ```

4. Reload VS Code.
5. Open any workspace and run an Agent Hub command from the Command Palette.

Packaged builds include the Agent Hub Python backend. A source checkout can
still use `.\install.ps1` if you want a local editable `.venv`.

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

## Common Settings

- `agentHub.serverUrl`: local Agent-Hub server URL. Default:
  `http://127.0.0.1:8787`
- `agentHub.pythonPath`: Python executable or launcher. Default: `auto`
- `agentHub.configPath`: config file path. Default: `agent-hub.config.json`
- `agentHub.agentProviderMode`: `local`, `hybrid`, or `cloud`. Default: `cloud`
- `agentHub.autoStart`: automatically start the server when needed. Default:
  `true`

## Local Model Aliases

Agent Hub is free/local by default. Generated workspace configs try
Codex/Claude-style aliases first. Those names point to local
OpenAI-compatible servers unless you explicitly configure hosted providers. When
LM Studio is available with a loaded model, the extension prefers it at
`http://127.0.0.1:1234`; otherwise it uses Ollama at
`http://127.0.0.1:11434`:

- `codex` -> the loaded LM Studio model, or `qwen2.5-coder:7b` through Ollama
- `claude` -> `qwen2.5-coder:7b`
- `gemini` -> `gemma3:4b`
- `chatgpt` -> `llama3.2`

Use the chat panel's `Pull Ollama Models` button to pull those Ollama defaults.
Official Claude, Gemini, and ChatGPT models are not downloadable into Ollama or
LM Studio; these aliases give the extension familiar names while staying local.

Ollama's Launch page shows integrations such as Claude Code, Codex App, Hermes
Agent, and OpenClaw. They are not model IDs; Agent Hub uses the models reported
by `ollama list`, then those integrations can be launched separately with
`ollama launch <integration> --model <model>`.

To see available local model servers, run:

```powershell
python -m agent_hub local-models
```

After changing provider settings, restart the Agent-Hub server.

## Development

To test the extension from source:

1. Open `vscode-extension` in VS Code.
2. Press `F5` to launch an Extension Development Host.
3. In the new VS Code window, open the Agent-Hub repository folder.

To package the extension:

```powershell
cd vscode-extension
npm run package
```
