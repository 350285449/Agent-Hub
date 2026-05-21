# Agent Hub VS Code Extension Update

## Next release

- Target version: `0.4.4`
- Purpose: publish Ollama-first routing defaults to the VS Code Marketplace

## Summary

This update file records the next VS Code extension release and the key change set for the extension.

- Local shell tool support remains enabled by default through `agentHub.allowShellTools`.
- The extension package now stages the Agent Hub Python backend into the VSIX.
- Startup uses the bundled backend when available and auto-detects a usable Python 3.11+ runtime.
- Config repair now writes Ollama/local models before Claude/Gemini/ChatGPT-style fallbacks.
- If Ollama is running with a coder model, the generated route uses it first; LM Studio remains a fallback.
- The chat UI can pull all Ollama alias defaults: `qwen2.5-coder:7b`, `gemma3:4b`, and `llama3.2`.

## Packaging

To build the extension package:

```powershell
cd vscode-extension
npm install
npm run package
```

The resulting `.vsix` can be installed locally or published with `npm run publish`.

## Notes

- The current `package.json` version is `0.4.4`.
- If you want this release to be published, run `npm run package` and install/publish the resulting `0.4.4` VSIX.
