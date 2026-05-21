# Agent Hub VS Code Extension Update

## Next release

- Target version: `0.4.16`
- Purpose: publish the chat Settings menu alongside hosted cloud control by default, explicit local control selection, API key management, local model selection, fast local finalization for file edits, and shell-first workspace-agent behavior

## Summary

This update file records the next VS Code extension release and the key change set for the extension.

- VS Code agent requests now default to the hosted `cloud-agent` route.
- Marketplace display name is now `Agent Hub Workspace` to avoid the taken `Agent Hub` name.
- Generated configs use hosted `codex`, `claude`, `gemini`, and `chatgpt` control providers by default.
- The chat UI can switch between Cloud, Hybrid, and Local control per request.
- The chat UI can pull the default Ollama local control model and select Local control.
- Chat and agent requests include the active editor path even when the webview has focus.
- Backend file tools can resolve a unique bare filename such as `config.py` inside the workspace.
- Ambiguous bare filenames are reported with workspace-relative path options.
- Local shell tool support remains enabled by default through `agentHub.allowShellTools`.
- Agent chat requests now stream live model/tool progress while work is running.
- Generated workspace configs enable `allow_shell_tools` by default.
- Chat now reports server, shell-tool, and local model-backend connection status before asking the model.
- Stale pre-streaming Agent Hub servers are detected and restarted when possible.
- Bare filename tool calls such as `config.py` now prefer the active editor path from request context.
- Workspace-agent progress now says it is planning and selecting tools instead of asking the model for the next action.
- Already-running backend servers that lack the current feature flags are restarted automatically.
- Agent requests include the current folder path and the files in that folder.
- Shell command use is called out directly in the agent prompt, and backend command timeouts can run longer local jobs.
- Agent prompts now explicitly require `write_file`/`replace_in_file` when users ask to create, edit, fix, update, or implement.
- Backend health reports file write tool support so stale servers are not reused.
- Successful `write_file` and `replace_in_file` calls now finalize locally without another Ollama validation turn.
- The extension package now stages the Agent Hub Python backend into the VSIX.
- Startup uses the bundled backend when available and auto-detects a usable Python 3.11+ runtime.
- Config repair now upgrades generated local-backed cloud aliases into hosted control providers plus explicit local routes.
- If Ollama is running with a coder model, the Local control route uses it; LM Studio remains a local fallback.
- The chat UI can save provider API keys into VS Code secret storage and inject them into Agent Hub on startup.
- The chat UI scans LM Studio and Ollama for installed local models before offering Ollama install choices with approximate storage sizes.
- A one-command installer now packages the VSIX, detects the VS Code CLI, installs the extension, and warns when Python 3.11+ is missing.
- The chat header now has a Settings menu for provider mode, server settings, local model selection, output access, API keys, and server actions.

## Packaging

To package and install the extension from the repository root:

```powershell
.\install-extension.ps1
```

On macOS or Linux:

```sh
sh ./install-extension.sh
```

To build only, run `node vscode-extension/scripts/install-extension.js --package-only`.
The resulting `.vsix` can be published with `npm run publish` from `vscode-extension`.

## Notes

- The current `package.json` version is `0.4.16`.
- If you want this release to be published, run `npm run package` from `vscode-extension` and publish the resulting `0.4.16` VSIX.
