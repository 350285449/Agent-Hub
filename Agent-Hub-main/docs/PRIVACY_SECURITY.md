# Privacy And Security

Before cloud provider use, Agent Hub treats repository files as untrusted data,
detects prompt-injection-like instructions, scans for secrets and sensitive
paths, redacts detected secret values, and evaluates the target provider's
privacy policy. Providers can be marked `local_only`, `safe_for_code`,
`safe_for_secrets`, or `never_send_workspace_files`.

Agent Hub does not install packages, pull models, edit configs, spawn
processes, upload workspace data, or write files without permission in modes
that require approval. `readonly` blocks workspace mutation. `safe` requires
approval for risky operations and blocks critical commands.

API keys saved through the VS Code extension are stored in VS Code Secret
Storage and injected into the backend environment when the server is started.

Provider keys and authorization-like headers are masked before being exposed by
security helper models. Plugin discovery is sandboxed to configured local
plugin directories and is manifest-first: Agent Hub validates plugin metadata,
entrypoint paths, trust registry entries, manifest hashes, and optional
signatures before any trusted local-process execution is allowed.

When the HTTP server is bound to a public host, every endpoint requires
`Authorization: Bearer <token>` or `X-Agent-Hub-API-Token`. Set
`api_auth_token_env`; the server refuses to start publicly without a token.
The legacy diagnostics token remains accepted for compatibility.

Approval booleans such as `approval_granted` and `approved` are ignored when
they arrive only in request JSON. Approval is honored only when the request has
an in-process trusted-session marker created after a valid
`X-Agent-Hub-Approval-Token`. The VS Code extension creates a per-process
approval token when it launches the backend.

Enterprise permissions are optional; when
`enterprise_mode_enabled` is true, sensitive provider and tool actions are
checked against configured users, roles, and grants.

When enterprise mode is enabled, every sensitive permission decision is written
to `.agent-hub/state/enterprise_audit.jsonl` with user, workspace, action,
resource, allow/deny, reason, and timestamp. Audit rows are redacted before
storage and before the diagnostics endpoint returns them. Audit exports can be
filtered by user, workspace, action, allow/deny, and date range; set
`enterprise_audit_retention_days` to limit exported diagnostics to recent
events.
