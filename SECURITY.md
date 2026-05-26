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
- Agent-Hub classifies providers as `LOCAL`, `TRUSTED_CLOUD`, or
  `UNTRUSTED_EXTERNAL`. Local providers are allowed, trusted cloud providers can
  be allowed non-interactively in `approval_mode=auto` or
  `cline_compatibility_mode=true`, and unknown external endpoints may still
  require explicit approval.
- Cline/Continue/Claude Code/VS Code compatibility mode removes only the
  interactive cloud-provider prompt for trusted IDE routing. It does not disable
  tool permissions, shell policy, path validation, secret detection, or
  dangerous-command blocking.
- Provider routing and compatibility decisions are audited in
  `.agent-hub/state/security_audit.jsonl`. Audit entries record provider,
  trust level, workspace-content presence, timestamp, and route decision without
  storing prompt text.
- File writes and shell execution are guarded by the permission layer.
- File tools resolve paths under `workspace_dir` and reject workspace escapes.
- Shell tools respect `allow_shell_tools`, `shell_command_policy`, and
  dangerous-command blocking before execution.
- Packaged VSIX builds exclude local configs, logs, provider health, state
  folders, and existing VSIX artifacts.
- Keep `approval_mode` conservative for untrusted workspaces.

If an IDE sees `agent_hub_permission_required`, enable compatibility mode for
trusted cloud routing:

```json
{
  "approval_mode": "auto",
  "cline_compatibility_mode": true,
  "tool_loop_enabled": true
}
```

Do not use compatibility mode to trust arbitrary external base URLs. Prefer a
known provider type such as `openrouter`, `groq`, `openai`, `anthropic`,
`gemini`, or a local/private `base_url`.
