# Plugin Sandbox

Plugin execution has four named backend states:

- `disabled`: default state; manifests are inventory only.
- `local_process`: trusted local execution with explicit capability scopes.
- `docker`: reserved backend for container isolation.
- `wasm`: reserved backend for capability-limited portable execution.

Remote MCP servers are treated as tool/provider adapters and must still pass
the same policy checks before execution.
