# Security Policy

Agent-Hub can route prompts to external providers and can execute local tools.
Treat configuration and workspace access as sensitive.

## Supported Versions

Security fixes are applied to the main branch first. Use the latest released
package or checkout when possible.

## Reporting a Vulnerability

Please open a private security advisory if available, or contact the project
maintainers with:

- A description of the issue.
- Reproduction steps.
- Impacted endpoints, tools, or providers.
- Whether secrets, files, shell commands, or external provider calls are
  involved.

## Security Notes

- Do not commit `agent-hub.config.json`, config backups, `.agent-hub/`, API
  keys, provider health state, logs, or packaged `.vsix` artifacts.
- External provider calls may transmit prompt and workspace context.
- File writes and shell execution are guarded by the permission layer.
- Keep `approval_mode` conservative for untrusted workspaces.
