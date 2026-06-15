# Security Boundaries

Agent-Hub treats provider calls, tool execution, plugin execution, repository
context, diagnostics, and extension requests as separate trust boundaries.

## Boundary Rules

- API requests are parsed into internal request objects before routing.
- Provider requests pass through provider permission policy and secret scanning.
- Tool requests pass through centralized policy checks before file, shell, or
  network access.
- Plugin manifests can be inspected without code execution.
- Plugin execution is denied by default and requires explicit trust, scopes,
  and a sandbox backend.
- Diagnostics and bundles must redact secrets before leaving the local process.
