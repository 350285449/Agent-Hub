# Install From VSIX

Build or install the packaged VS Code extension:

```sh
cd vscode-extension
npm install
npm run compile
npm run prepare-backend
npx vsce package
code --install-extension agent-hub-vscode-0.7.5.vsix
```

Start the backend from the repository or from the extension command:

```sh
python -m agent_hub serve
```

Cline:

- Base URL: `http://127.0.0.1:8787/v1`
- API key: `local-agent-hub-token`
- Model: `agent-hub-coding`

Continue:

```json
{
  "title": "Agent-Hub",
  "provider": "openai",
  "model": "agent-hub-coding",
  "apiBase": "http://127.0.0.1:8787/v1",
  "apiKey": "local-agent-hub-token"
}
```

Packaged builds exclude local config, logs, provider health state, `.agent-hub`
state folders, and existing `.vsix` artifacts.
