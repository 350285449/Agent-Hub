# Agent Hub VS Code Extension

This extension connects VS Code to the local Agent-Hub server in this repo.

## Run From This GitHub Repo

1. Open the repository root in VS Code.
2. Install the Python package and starter config:

   ```powershell
   .\install.ps1
   ```

   Or, if you do not want the helper script, make sure the Python package works:

   ```powershell
   python -m agent_hub doctor
   ```

3. Open `vscode-extension` in a second VS Code window, or use `File > Open Folder...`
   and choose `vscode-extension`.
4. Press `F5` to launch an Extension Development Host.
5. In the Extension Development Host, open the Agent-Hub repository folder.
6. Run commands from the Command Palette:

   - `Agent Hub: Open Codex Chat`
   - `Agent Hub: Start Server`
   - `Agent Hub: Show Status`
   - `Agent Hub: Ask Agent`
   - `Agent Hub: Run Local Coding Agent`
   - `Agent Hub: Research Web`
   - `Agent Hub: Explain Selection`
   - `Agent Hub: Explain Current File`

The extension starts `python -m agent_hub --config <path> serve --watch-inbox`
from your workspace folder when `agentHub.autoStart` is enabled.

## Settings

- `agentHub.serverUrl`: Agent-Hub URL. Default: `http://127.0.0.1:8787`
- `agentHub.pythonPath`: Python executable. Default: `python`; auto-detects workspace `.venv` first.
- `agentHub.configPath`: config file path. Default: `agent-hub.config.json`
- `agentHub.route`: route sent to Agent-Hub. Default: `coding`
- `agentHub.codingAgentRoute`: route used by `Agent Hub: Run Local Coding Agent`. Default: `local-agent`
- `agentHub.agentProviderMode`: `local`, `hybrid`, or `cloud`. Default: `local`
- `agentHub.researchRoute`: route used by `Agent Hub: Research Web`. Default: `research`
- `agentHub.agentMaxSteps`: maximum local agent tool steps. Default: `20`
- `agentHub.allowShellTools`: allow the local coding agent to run shell commands. Default: `true`
- `agentHub.maxTokens`: response token budget. Default: `1200`
- `agentHub.autoStart`: start the server when a request is sent. Default: `true`

## Agent Compatibility

The extension talks to Agent-Hub's native endpoints. Agent commands use
`/v1/agent`, while research uses `/v1/route` so web-grounded providers can return
normal answers with source metadata. Provider compatibility lives in Agent-Hub
itself, so the same VS Code commands can route to local/free agents,
Gemma/Gema-style local models, ChatGPT/OpenAI, Gemini, or Claude
depending on your `agent-hub.config.json`.

`free_only` remains enabled by default, so cloud providers in the example config
stay skipped unless you intentionally enable them later.

`Agent Hub: Open Codex Chat` is the easiest Codex-like path. It opens a real
chat view, reuses one session for conversation history, can include the current
selection, and auto-starts the local Agent-Hub server when `agentHub.autoStart`
is enabled.
It needs one local OpenAI-compatible model online, such as Ollama or LM Studio,
unless you intentionally opt in to a cloud provider.

`Agent Hub: Run Local Coding Agent` is the one-shot Codex-like path. It uses the
`local-agent` route, which points only at free local OpenAI-compatible model
servers such as Ollama, LM Studio, LocalAI, vLLM, or your configured
`custom-local` endpoint. It gives the agent workspace tools for listing,
reading, searching, writing, targeted replacements, and optional local shell
verification. No cloud model or paid API is used by default.

Run `python -m agent_hub local-models` from the repo root to see which local
model servers are online and which model IDs they expose.

Cloud providers are opt-in. Enable one in `agent-hub.config.json` with:

```powershell
python -m agent_hub enable-provider openai --model your-openai-model
python -m agent_hub enable-provider claude --model your-claude-model
python -m agent_hub enable-provider gemini --model your-gemini-model
```

Then set `agentHub.agentProviderMode` to `hybrid` or `cloud` in VS Code. The
server must be restarted after changing provider config.

Model failover is silent by default. If a local model cannot fit the request or
hits a token/context limit, Agent-Hub tries the next free local model while the
VS Code user sees the same command and one final answer. Set
`expose_routing_details` in `agent-hub.config.json` only for debugging.

`Agent Hub: Research Web` uses the native `/v1/route` endpoint and the
`research` route. By default that route uses the built-in `local-research`
provider, which does free extractive web research from this machine and returns
citations and search results without a cloud LLM or API key.

It still uses your normal internet connection to search and fetch public pages;
all synthesis and source extraction happens locally inside Agent-Hub.

## Package And Publish

Install the VS Code publishing tool:

```powershell
cd vscode-extension
npm install --save-dev @vscode/vsce
npm run package
```

That creates a `.vsix` file you can install locally from VS Code with
`Extensions: Install from VSIX...`.

To publish to the Visual Studio Marketplace:

1. Create a publisher in the Visual Studio Marketplace.
2. Replace `publisher` in `package.json` with your Marketplace publisher ID.
3. Create an Azure DevOps personal access token with Marketplace publishing access.
4. Sign in and publish:

```powershell
npx @vscode/vsce login your-publisher-id
npm run publish
```
