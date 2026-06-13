# Security Boundaries

Agent-Hub treats provider calls, workspace tools, shell commands, installs,
config edits, and workflow file actions as explicit boundaries.

## Provider Boundary

External provider calls are checked by `ProviderPermissionPolicy`. Unknown
external OpenAI-compatible endpoints require explicit approval, trusted providers
are audited, and local/private endpoints are treated separately.

Provider permission events are recorded in security audit logs without raw
prompt bodies or secrets.

## Tool Boundary

Tool calls go through:

- `ToolRegistry`
- `ToolPermissionLayer`
- `PermissionManager`
- `ToolExecutionPipeline`
- `AgentToolbox` for workspace-facing agent tools

Protected actions include file writes, file deletes, config edits, package
installs, shell commands, external downloads, uploads, process control, and
secret-bearing content.

## Workflow Boundary

Workflows do not directly touch files or run shell commands. Workflow-owned
actions use `SafeWorkspaceService`, which delegates to `AgentToolbox` so the
same permission, checkpoint, rollback, and dry-run behavior applies.

Workflow support includes:

- per-stage timeout handling
- cancellation checks before each stage
- dry-run file/shell action previews
- validation commands routed through workspace permissions
- workflow progress events in `.agent-hub/state/workflow_execution.jsonl`

## Filesystem Boundary

Workspace paths are resolved under `workspace_dir`; path escapes are rejected.
Mutating file tools create checkpoints before edits and can roll back on
failure. Dry-run mode returns patch previews without changing files.

## Shell Boundary

Shell commands are parsed without `shell=True`, restricted to allowlisted
executables, and blocked when they contain shell operators, destructive admin
patterns, or downloaded install scripts. Package manager commands and mutating
commands are high risk and require approval in ask/safe modes.

## API Boundary

OpenAI, Anthropic, and OpenRouter-compatible endpoints do not include internal
workflow or routing metadata by default. Routing details appear only when
`expose_routing_details=true` or when a native/diagnostic endpoint explicitly
requests them.
