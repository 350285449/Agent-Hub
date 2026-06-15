# Agent-Hub Threat Model

## Scope

This threat model covers the local Agent-Hub backend, VS Code extension,
provider routing, workspace tools, MCP/plugin execution, diagnostics, local
state, and compatibility APIs. It assumes Agent-Hub usually runs on a developer
machine and may optionally bind beyond localhost only when authentication is
configured.

## Assets

- Workspace files, repository metadata, active editor context, and patches.
- Provider API keys, generated local API tokens, approval tokens, and plugin
  trust material.
- Prompt, tool, routing, benchmark, and workflow logs in `.agent-hub/state`.
- Provider/model selection history, routing memory, and benchmark proof data.
- User-owned quotas, cloud-provider accounts, and local model servers.

## Trust Boundaries

| Boundary | Trusted Side | Untrusted Or Less-Trusted Side | Main Controls |
| --- | --- | --- | --- |
| HTTP API | Local Agent-Hub process | API clients, public network callers | local auth tokens, public-bind refusal without auth, request-size limits, CORS |
| Provider calls | Local router and policy service | Cloud and external OpenAI-compatible endpoints | provider privacy mode, explicit approval, secret scanning, provider trust level |
| Workspace tools | Permissioned tool runtime | Model-generated tool requests | path validation, shell classifier, approval modes, workspace trust |
| Plugins/MCP | Manifest/trust registry and policy service | Third-party plugin or MCP process | deny-by-default execution, capability scopes, sandbox backend, timeout |
| Diagnostics | Redacted local dashboards | Browser/webview/API consumers | diagnostics auth, redaction, feature-specific endpoint guards |
| Repository context | User workspace | Model prompt context | prompt-injection detection, protected categories, context compaction |

## Threats And Mitigations

### Unauthorized Local Or Network Access

Threat: another local process or a network caller sends requests to Agent-Hub.

Mitigations:

- Public binds require API authentication before the server starts.
- Local authenticated mode generates credentials outside normal config files.
- CORS rejects unknown browser origins while allowing VS Code webviews.
- Request bodies have size limits and rate limits apply on public binds.

Residual risk: a compromised local user account can usually access local
developer processes. Treat Agent-Hub as part of the user trust domain.

### Secret Exfiltration To Providers

Threat: prompts, workspace context, or tool results include secrets and are sent
to cloud or unknown external providers.

Mitigations:

- Provider permission policy classifies local, trusted cloud, and unknown
  external endpoints.
- Secret scanning and prompt-injection scanning feed provider approval policy.
- Provider privacy flags can block workspace files, code, or secrets for a
  provider.
- `approval_mode=safe` is the default guarded posture.

Residual risk: deterministic scanners can miss novel secret formats or secrets
embedded in binary/generated content.

### Model-Generated Dangerous Tool Calls

Threat: a model asks Agent-Hub to delete files, run destructive shell commands,
install packages, or upload workspace content.

Mitigations:

- `PolicyService` is the central facade for tool/provider decisions.
- Shell commands are classified into safe, moderate, and dangerous tiers.
- Critical destructive patterns are blocked even in auto mode.
- File writes, deletes, config edits, package installs, and process control
  require explicit policy decisions.
- Untrusted workspaces force read-only behavior for sensitive actions.

Residual risk: benign-looking commands can still have side effects through
project scripts. Keep shell tools disabled unless needed.

### Plugin Or MCP Compromise

Threat: a plugin or MCP server executes arbitrary local code or declares
misleading capabilities.

Mitigations:

- Plugin execution is deny-by-default.
- Validation and capability inventory run without executing plugin code.
- Trusted plugins require config allowlist, manifest signature, or trust
  registry entry.
- Capability scopes and sandbox policy gate local-process execution.
- MCP stdio execution is disabled unless explicitly enabled.

Residual risk: once enabled, trusted local-process plugins run with the
permissions of the Agent-Hub process. Docker/WASM isolation remains future work.

### Prompt Injection Through Repository Context

Threat: repository files or tool outputs contain instructions that try to
override user intent or leak data.

Mitigations:

- Prompt-injection detection flags suspicious context.
- Repository context is marked as workspace evidence rather than trusted
  instructions.
- Context compaction preserves protected client/task state while reducing old
  tool noise.

Residual risk: LLMs may still follow malicious text in retrieved files. High
risk tasks should use reviewer/validator workflows and local-only providers
when confidentiality matters.

### Misleading Proof Or Readiness Claims

Threat: dashboards imply real runtime readiness or savings without measured
provider evidence.

Mitigations:

- Feature scorecard separates local contract proof from runtime usability.
- Proof commands and benchmark reports include dataset and measurement context.
- Runtime readiness requires backend reachability, verified coding provider,
  guarded permissions, and route smoke evidence.

Residual risk: external provider quality and uptime remain outside local
control; benchmark claims should always name dataset, date, route, and baseline.

## Security Roadmap Tie-In

- Phase 8 observability: trace IDs now give a stable contract for stitching API,
  routing, provider, tool, workflow, and permission events.
- Phase 9 policy hardening: `PolicyService` is the migration point for
  provider, tool, plugin, MCP, and workspace policy decisions.
- Phase 10 developer platform: `/openapi.json` documents stable API surfaces so
  clients can build against explicit contracts.

## Operational Recommendations

- Keep `approval_mode=safe` for daily use.
- Use local routes for private repositories or sensitive files.
- Enable plugin and MCP execution only for trusted sources and scoped tasks.
- Run `agent-hub proof run --coding` before publishing performance claims.
- Review `/v1/readiness`, `/v1/feature-scorecard`, and `/v1/plugins` before
  enabling public bind, cloud providers, plugins, or MCP execution.
