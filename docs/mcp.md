# MCP Bridge

Agent-Hub now has a bridge shape for external MCP servers.

## Current Support

- `mcp_servers` can be declared in config.
- Declared MCP tool metadata is normalized into Agent-Hub `Tool` objects.
- MCP-shaped tools use the same registry and permission pipeline as built-ins.
- External protocol execution is marked `future_ready` and returns a clear
  unsupported result.

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

## Future Plan

The next bridge step is a real stdio/SSE MCP client that discovers tools at
server startup, executes calls through the same permission layer, and streams
tool events into the dashboard.
