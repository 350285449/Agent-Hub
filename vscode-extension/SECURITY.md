# Security Policy

Agent Hub routes prompts to local and external model providers, and it can run
permissioned workspace tools. Treat configuration, logs, provider endpoints,
API keys, and workspace access as sensitive.

## Supported Versions

Security fixes are applied to the main branch first. Use the latest Marketplace
release or the latest packaged VSIX when possible.

## Reporting a Vulnerability

Please open a private security advisory if available, or report the issue at:

https://github.com/350285449/Agent-Hub/issues

Include:

- A description of the issue.
- Reproduction steps.
- Impacted endpoints, tools, providers, or VS Code commands.
- Whether secrets, files, shell commands, or external provider calls are
  involved.

## Security Notes

- Do not commit `agent-hub.config.json`, `.agent-hub/`, API keys, provider
  health state, logs, or packaged `.vsix` artifacts.
- External provider calls may transmit prompt and workspace context.
- File writes and shell execution are guarded by the permission layer.
- File tools resolve paths under the workspace and reject workspace escapes.
- Shell tools respect `allow_shell_tools`, `shell_command_policy`, and
  dangerous-command blocking before execution.
- Keep `agentHub.approvalMode` conservative for untrusted workspaces.
- Cline, Roo Code, Continue, Claude Code, and VS Code compatibility settings do
  not disable path validation, secret detection, shell policy, or dangerous
  command blocking.
