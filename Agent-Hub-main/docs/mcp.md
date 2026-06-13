# MCP Bridge

Agent-Hub now has a bridge shape for external MCP servers.

## Current Support

- `mcp_servers` can be declared in config.
- Declared MCP tool metadata is normalized into Agent-Hub `Tool` objects.
- MCP-shaped tools use the same registry and permission pipeline as built-ins.
- Stdio MCP execution is available when `mcp_execution_enabled` is true and the
  server has a configured `command`. Execution is still off by default.
- Tool calls use a bounded JSON-RPC initialize plus `tools/call` exchange and
  respect the configured `mcp_timeout_seconds`.
- `GET /v1/mcp/status` reports per-server status, per-tool permissions,
  input-property inventory, sample call payloads, timeout policy, and an
  operational-readiness score. This makes a no-execution review possible before
  enabling external MCP processes.

## Example

```json
{
  "mcp_servers": [
    {
      "name": "local",
      "enabled": true,
      "command": "npx",
      "args": ["-y", "example-mcp-server"],
      "tools": [
        {
          "name": "lookup",
          "description": "Lookup a symbol",
          "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
          "permissions": ["read"]
        }
      ]
    }
  ]
}
```

The normalized tool name is `mcp.local.lookup`.

Status output includes a call example for each declared tool:

```json
{
  "name": "mcp.local.lookup",
  "arguments": {"query": ""}
}
```

## Safety

MCP servers are external processes. Keep `mcp_execution_enabled` false unless
you trust the configured command and tool definitions. Agent Hub launches the
server without a shell and times out tool calls, but it does not sandbox the
external process.
