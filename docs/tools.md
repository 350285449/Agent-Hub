# Tools And MCP Compatibility

`agent_hub.tools` is an MCP-compatible internal abstraction layer. It prepares
Agent-Hub to bridge external MCP servers later without coupling the router to a
specific MCP runtime.

## Types

- `Tool`: name, description, JSON schema, executor, permission metadata.
- `ToolCall`: normalized invocation with id, name, and arguments.
- `ToolResult`: normalized result with `ok`, content, error, timings, and
  metadata.

## Registry And Pipeline

`ToolRegistry` stores available tools. `ToolExecutionPipeline` resolves calls,
checks permissions, executes the tool, and logs tool events.

## Built-In Tools

- `file_read`
- `file_write`
- `shell_execute`
- `search_repo`

All built-ins are workspace-scoped. File paths must stay inside
`workspace_dir`. Shell execution is local and subject to `approval_mode` and
tool permission checks.

## OpenAI Tool Schemas

Use `openai_tool_specs(registry)` to expose registered tools as
OpenAI-compatible `tools` entries. Tool calls can be normalized with
`ToolCall.from_openai(...)`.

## Future MCP Bridge

The future bridge should adapt external MCP tools into `Tool` objects, stream
tool execution events through the same pipeline, and preserve the same
permission checks.
