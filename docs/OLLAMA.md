# Ollama Setup

Agent Hub can use Ollama in two ways:

- Local control through the Ollama server at `http://127.0.0.1:11434`.
- Hosted Ollama Cloud entries when you provide `OLLAMA_API_KEY`.

## Local Setup

Install Ollama, start it, and pull a coding-friendly local model:

```powershell
ollama pull qwen2.5-coder:7b
ollama serve
```

Then verify from Agent Hub:

```powershell
agent-hub local-models
agent-hub doctor
```

If `agent-hub local-models` shows the server as offline, confirm that Ollama is
listening on `http://127.0.0.1:11434` and that no firewall or port conflict is
blocking localhost.

## Config

Fresh configs include local Ollama entries on the `local-agent` route. To force
local-only routing for coding work:

```powershell
agent-hub agent --route local-agent --allow-shell-tools "inspect this repo"
```

You can override the detected model ID with:

```powershell
$env:AGENT_HUB_OLLAMA_CODER_MODEL = "qwen2.5-coder:7b"
```

Use `agent-hub doctor --json` when diagnosing route choices; it reports enabled
providers, local server status, backend reachability, and exact fixes.

## VS Code

In the Agent Hub sidebar, set provider mode to `Local` when you want direct
local-only control. Use `Cloud` or `Hybrid` only when you intentionally want the
configured cloud route to participate.
