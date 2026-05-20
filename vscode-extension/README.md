# Agent Hub

Run Agent-Hub from VS Code and send coding, research, and explanation requests
to your local Agent-Hub server.

## Quick Start

1. Open the Agent-Hub repository in VS Code.
2. Make sure the Python package works:

   ```powershell
   python -m agent_hub doctor
   ```

3. Install the extension from the packaged `.vsix`:

   ```powershell
   cd vscode-extension
   npm run package
   $env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd --install-extension .\agent-hub-vscode-0.2.0.vsix --force
   ```

4. Reload VS Code.
5. Run an Agent Hub command from the Command Palette.

## Commands

- `Agent Hub: Open Codex Chat`
- `Agent Hub: Start Server`
- `Agent Hub: Show Status`
- `Agent Hub: Ask Agent`
- `Agent Hub: Run Local Coding Agent`
- `Agent Hub: Research Web`
- `Agent Hub: Explain Selection`
- `Agent Hub: Explain Current File`

When `agentHub.autoStart` is enabled, the extension starts the local server for
you before sending a request.

## Common Settings

- `agentHub.serverUrl`: local Agent-Hub server URL. Default:
  `http://127.0.0.1:8787`
- `agentHub.pythonPath`: Python executable. Default: `python`
- `agentHub.configPath`: config file path. Default: `agent-hub.config.json`
- `agentHub.agentProviderMode`: `local`, `hybrid`, or `cloud`. Default: `local`
- `agentHub.autoStart`: automatically start the server when needed. Default:
  `true`

## Local And Cloud Models

Agent Hub uses local/free providers by default. Cloud providers are opt-in and
must be enabled in `agent-hub.config.json`.

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
