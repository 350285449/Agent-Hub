# Changelog

## Unreleased

- Adds a one-command cross-platform installer for packaging and installing the VS Code extension from a checkout.
- Detects VS Code, VS Code Insiders, or VSCodium CLI paths and warns when Python 3.11+ is missing.

## 0.4.15

- Adds an API Keys panel that stores OpenAI, Anthropic, and Gemini keys in VS Code secret storage.
- Injects saved provider keys into the Agent Hub server environment on startup.
- Replaces the pull-only local model button with a chooser for installed LM Studio/Ollama models.
- Shows recommended Ollama install choices with approximate storage sizes when no local model is found.

## 0.4.14

- Makes hosted cloud providers the default control-agent route.
- Adds a chat control selector plus a `Pull Local Control Model` action for local Ollama control.
- Uses a unique Marketplace display name, `Agent Hub Workspace`.

## 0.4.13

- Makes hosted cloud providers the default control-agent route.
- Adds a chat control selector plus a `Pull Local Control Model` action for local Ollama control.

## 0.4.12

- Fast-finalizes successful `write_file` and `replace_in_file` calls locally, avoiding an extra Ollama round-trip after file edits.
- Adds a `fast_write_finalize` backend feature flag and request option.

## 0.4.11

- Makes create/edit behavior explicit in all agent prompts: create with `write_file`, edit with `replace_in_file`, then finalize.
- Adds a backend feature flag for file write tools so stale backend processes are restarted.
- Updates the chat prompt placeholder to include create, edit, and command-running workflows.

## 0.4.10

- Restarts already-running backend servers that lack the active-file resolver and current-folder feature flags.
- Sends the active editor's current folder and folder file list with agent requests.
- Makes shell command access clearer in agent prompts and allows longer local command timeouts.

## 0.4.9

- Prefers the active editor path from request context when resolving bare filenames such as `config.py`.
- Prevents ambiguous basename tool failures from bouncing the agent through extra model steps.
- Updates workspace-agent progress wording to describe Agent Hub planning and tool selection more directly.

## 0.4.8

- Detects stale pre-streaming Agent Hub servers and restarts them when possible.
- Shows server, route, shell-tool, and local model-backend connection status in chat.
- Adds watchdog progress messages when the server or model backend has not answered yet.

## 0.4.7

- Streams live Agent Hub step/tool progress into the chat panel.
- Enables shell tools in generated workspace configs by default.
- Bundles native backend agent streaming support.

## 0.4.6

- Defaults VS Code agent requests to the cloud-style route.
- Adds a local `codex` alias and routes Codex/Claude-style agents before direct local fallbacks.
- Prefers LM Studio for generated cloud-style aliases when a model is loaded, with Ollama as fallback.

## 0.4.5

- Sends the active editor path with chat and agent requests so basename prompts target the open file.
- Bundles backend file-tool resolution for unique bare filenames such as `config.py`.
- Reports ambiguous bare filenames with concrete workspace-relative path options.

## 0.4.4

- Makes the extension default to Ollama-first hybrid routing.
- Generates workspace configs with the Ollama coder model before Claude/Gemini/ChatGPT-style fallbacks.
- Bundles the updated Agent-Hub backend with local-first defaults.

## 0.4.3

- Repairs older minimal Ollama workspace configs into Claude/Gemini/ChatGPT-style local aliases.
- Reuses the detected Ollama model for local aliases so installed models are selected automatically.
- Bundles Agent-Hub agent-loop fixes for malformed tool calls and echo fallback handling.

## 0.4.2

- Changes Claude, Gemini, and ChatGPT from vendor API defaults into local OpenAI-compatible aliases.
- Uses a detected LM Studio model for those aliases when LM Studio is running; otherwise defaults to Ollama models.
- Pulls all default Ollama alias models from the chat UI.

## 0.4.1

- Added preliminary `cloud` provider-mode routing for Claude, Gemini, and ChatGPT agent names.
- Changed the VS Code default provider mode to `cloud` with local model fallback.
- Kept LM Studio and Ollama as fallback providers in generated workspace configs.

## 0.4.0

- Added LM Studio detection for generated workspace configs.
- Creates local routes from detected LM Studio and Ollama models instead of hardcoding Ollama only.
- Changed `agentHub.pythonPath` default to `auto` and tries common Python 3.11+ launchers before failing.
- Renamed the chat button to `Pull Ollama Model` so LM Studio users are not sent down the wrong setup path.

## 0.3.9

- Bundles the Agent Hub Python backend into packaged VSIX builds.
- Starts the server with the bundled backend on `PYTHONPATH`, so a fresh workspace no longer needs `agent_hub` preinstalled.
- Repairs invalid local config JSON by backing it up and writing strict JSON.
- Improves missing Ollama/Python backend startup messages.

## 0.3.8

- Updated the extension package to version `0.3.8`.
- Continued support for local shell tool execution and agent integration.

## 0.3.6

- Tightened VS Code agent prompts to request raw JSON tool calls with quoted string arguments.
- Pairs with Agent Hub's malformed tool-call recovery for local models.

## 0.3.5

- Improved VS Code agent prompts so local models use Agent Hub file tools instead of showing tool-call JSON.
- Made response rendering handle additional native response shapes.

## 0.1.0

- Initial Agent Hub VS Code extension.
- Start/stop the local Agent-Hub server.
- Ask the workspace agent, explain selections/files, run local coding-agent tasks, and use local research.
- Supports local, hybrid, and cloud provider modes through Agent-Hub routes.

## 0.1.1

- Added Marketplace icon.

## 0.2.0

- Added `Agent Hub: Open Codex Chat` with session history, optional selection context, and auto-start support.
- Updated the extension icon and Codex Chat header with the Agent Hub logo.

## 0.2.1

- Simplified the extension README for local installation and day-to-day use.

## 0.3.0

- Added the native VS Code `@agenthub` chat participant.
- Renamed the custom chat tab to Agent Hub.

## 0.3.1

- Improved local model connection errors in the Agent Hub chat UI.

## 0.3.2

- Added a Pull Model button to install the default Ollama coding model.

## 0.3.3

- Added elapsed working status for slow local model requests.
- Increased the Agent Hub request timeout for CPU-based local models.

## 0.3.4

- Automatically creates a focused local config from detected Ollama models.
- Avoids offline local fallback providers when no explicit config exists.
