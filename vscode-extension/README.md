# Agent Hub VS Code Extension

This extension connects VS Code to the local Agent-Hub server in this repo.

## Run From This GitHub Repo

1. Open the repository root in VS Code.
2. Make sure the Python package works:

   ```powershell
   python -m agent_hub doctor
   ```

3. Open `vscode-extension` in a second VS Code window, or use `File > Open Folder...`
   and choose `vscode-extension`.
4. Press `F5` to launch an Extension Development Host.
5. In the Extension Development Host, open the Agent-Hub repository folder.
6. Run commands from the Command Palette:

   - `Agent Hub: Start Server`
   - `Agent Hub: Show Status`
   - `Agent Hub: Ask Agent`
   - `Agent Hub: Explain Selection`
   - `Agent Hub: Explain Current File`

The extension starts `python -m agent_hub --config <path> serve --watch-inbox`
from your workspace folder when `agentHub.autoStart` is enabled.

## Settings

- `agentHub.serverUrl`: Agent-Hub URL. Default: `http://127.0.0.1:8787`
- `agentHub.pythonPath`: Python executable. Default: `python`
- `agentHub.configPath`: config file path. Default: `agent-hub.config.json`
- `agentHub.route`: route sent to Agent-Hub. Default: `coding`
- `agentHub.maxTokens`: response token budget. Default: `1200`
- `agentHub.autoStart`: start the server when a request is sent. Default: `true`

## Agent Compatibility

The extension talks only to Agent-Hub's native `/v1/agent` endpoint. Provider
compatibility lives in Agent-Hub itself, so the same VS Code commands can route
to local/free agents, Gemma/Gema-style local models, ChatGPT/OpenAI, Gemini, or
Claude depending on your `agent-hub.config.json`.

`free_only` remains enabled by default, so cloud providers in the example config
stay skipped unless you intentionally enable them later.
