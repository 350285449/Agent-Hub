# Agent Hub - Multi-Provider AI Router

Use OpenAI, Claude, Gemini, Ollama, OpenRouter, local models, Cline, Roo Code,
Continue, and coding agents through one local API.

## Why Use Agent Hub?

- Route requests across local and cloud providers from one OpenAI-compatible API.
- Fail over when a model is offline, out of quota, overloaded, or too small for the context.
- Keep workspace tool use behind approvals, path limits, and command safety checks.
- Preserve Cline, Roo Code, Continue, and Claude Code tool/context payloads.
- Inspect provider health, token usage, routing decisions, limits, and logs in VS Code.

## Competitive Features

- Provider health dashboard with latency, quota, reliability, and cooldown state.
- Routing explanation logs so you can see why a model won or failed over.
- Cost and latency estimates for adaptive routing and workflow optimization.
- Presets for Private, Fast, Cheap, and Best Coding routing modes.
- Exportable debug bundle for Cline, provider, routing, and backend diagnostics.

## Demo

![Agent Hub demo](media/demo.gif)

If the Marketplace does not autoplay GIFs in your client, open the animation
from the repository media folder or use the screenshots below.

## Screenshots

![Agent Hub dashboard](media/dashboard.png)

![Provider routing](media/provider-routing.png)

![Cline setup](media/cline-setup.png)

## Install

1. Install the extension.
2. Install Python 3.11 or newer.
3. Open a project folder.

The Agent Hub backend is bundled with the VSIX.

## Use

1. Click the Agent Hub icon.
2. Click `Start`.
3. Type a task.
4. Click `Send`.

Click `Stop` when you are done.

Good first tasks:

- `Explain this file`
- `Find the bug`
- `Fix the failing test`
- `Add a small feature`

## Models

Pick one path:

- Open `Settings` and save an OpenAI, Claude, Gemini, Groq, OpenRouter, or other API key.
- Start Ollama or LM Studio locally and let Agent Hub route to the local endpoint.
- Connect Cline, Roo Code, Continue, Claude Code, or another OpenAI-compatible tool.

## Comparison

| Feature | Agent Hub | Single-provider extension |
| --- | --- | --- |
| Local and cloud models | Yes | Usually one provider |
| Cline/OpenAI-compatible endpoint | Yes | Varies |
| Provider fallback | Yes | Rare |
| Approval-gated workspace tools | Yes | Varies |
| Provider health and limit logs | Yes | Usually limited |

## Cline Setup

Choose `OpenAI Compatible` in Cline:

```text
Base URL: http://127.0.0.1:8787/v1
API Key: local-agent-hub-token
Model: agent-hub-coding
```

Use `Agent Hub: Copy Cline Config` and `Agent Hub: Test Cline Connection` from
the command palette to verify setup before a real task.

## Ollama Setup

1. Install Ollama.
2. Pull a coding model, for example `ollama pull qwen2.5-coder`.
3. Start the Ollama app or run `ollama serve`.
4. Click `Start` in Agent Hub, then open `Health` to confirm the local provider is reachable.

Local routes use `http://127.0.0.1:11434`. Hosted Ollama Cloud entries require
`OLLAMA_API_KEY` and are treated like other cloud providers.

## Provider Setup

- Ollama: install Ollama, pull a model, then start Agent Hub. Local routes use `http://127.0.0.1:11434`.
- LM Studio: start the local server, load a model, then use Settings to select the endpoint.
- OpenAI, Claude, Gemini, Groq, OpenRouter: save the provider API key in Settings and keep `approval_mode` at `ask` or `auto` based on your workflow.

## Safety

Agent Hub asks before sensitive file, shell, process, and provider actions.
Dangerous shell commands, path escapes, secret-like payloads, and unknown
external endpoints are blocked or routed through explicit approval.

## Troubleshooting

| Problem | What to Check | Fix |
| --- | --- | --- |
| Backend not running | Status bar or Health section says stopped | Click `Start`, or run `agent-hub doctor` in a terminal |
| No model available | Health shows no ready provider | Save an API key, start Ollama/LM Studio, or enable a provider |
| Cline error | Base URL/model mismatch | Use `http://127.0.0.1:8787/v1`, model `agent-hub-coding`, then run `Agent Hub: Test Cline Connection` |
| Slow or costly route | Routing logs show the wrong provider | Apply Private, Fast, Cheap, or Best Coding preset and inspect provider health |
| Packaging issue | VSIX backend is missing or stale | Run `cd vscode-extension && npm run prepare-backend` before packaging |
| Need support details | Logs are scattered | Use the debug bundle export and include routing/provider health output |

## More Help

- [Cline setup](https://github.com/350285449/Agent-Hub/blob/main/docs/CLINE.md)
- [Claude Code setup](https://github.com/350285449/Agent-Hub/blob/main/docs/CLAUDE_CODE.md)
- [Continue setup](https://github.com/350285449/Agent-Hub/blob/main/docs/continue.md)
- [Permissions](https://github.com/350285449/Agent-Hub/blob/main/docs/PERMISSIONS.md)
- [Troubleshooting](https://github.com/350285449/Agent-Hub/blob/main/docs/TROUBLESHOOTING.md)
