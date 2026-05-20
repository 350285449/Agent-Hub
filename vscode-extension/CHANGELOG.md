# Changelog

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
