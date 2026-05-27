# Privacy And Security

Before cloud provider use, Agent Hub evaluates provider permission, secret
findings, workspace context, and approval mode. Cloud transparency data includes
provider/model, token estimate, file/snippet hints, and secret findings when
available.

Agent Hub does not install packages, pull models, edit configs, spawn
processes, upload workspace data, or write files without permission in modes
that require approval. `readonly` blocks workspace mutation. `safe` requires
approval for risky operations and blocks critical commands.

API keys saved through the VS Code extension are stored in VS Code Secret
Storage and injected into the backend environment when the server is started.

Provider keys and authorization-like headers are masked before being exposed by
security helper models. Plugin discovery is sandboxed to configured local
plugin directories and is manifest-only: Agent Hub validates plugin metadata,
entrypoint paths, trust registry entries, manifest hashes, and optional
signatures, but does not execute plugin code.

When the HTTP server is bound to a public host, diagnostic endpoints such as
`/v1/provider-health`, `/v1/routing/status`, `/v1/limits`, `/v1/usage`,
`/v1/client-sources`, `/v1/events`, `/v1/tools`, `/v1/workflows/status`,
`/v1/plugins`, and `/v1/enterprise/audit` require a diagnostics token. Set
`diagnostics_auth_token_env` for
deployments. Enterprise permissions are optional; when
`enterprise_mode_enabled` is true, sensitive provider and tool actions are
checked against configured users, roles, and grants.

When enterprise mode is enabled, every sensitive permission decision is written
to `.agent-hub/state/enterprise_audit.jsonl` with user, workspace, action,
resource, allow/deny, reason, and timestamp. Audit rows are redacted before
storage and before the diagnostics endpoint returns them. Audit exports can be
filtered by user, workspace, action, allow/deny, and date range; set
`enterprise_audit_retention_days` to limit exported diagnostics to recent
events.
