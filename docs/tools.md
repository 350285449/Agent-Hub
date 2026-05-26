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

Aliases are registered for older client names:

- `read_file` -> `file_read`
- `write_file` -> `file_write`
- `run_command` -> `shell_execute`
- `search_files` -> `search_repo`

## Built-In Tools

- `file_read`
- `file_write`
- `shell_execute`
- `search_repo`

All built-ins are workspace-scoped. File paths must stay inside
`workspace_dir`. Shell execution is local and subject to `approval_mode` and
tool permission checks. Dangerous shell patterns such as recursive forced
delete, admin elevation, `git reset --hard`, and install-script piping are
blocked before execution. Denied tool calls are recorded in the tool event log.

## Runtime Tool Loop

When Agent-Hub owns the tool schema (`agent_hub_tools`) or injects built-in
tools for coding/repo tasks, provider responses with OpenAI-style `tool_calls`
are executed through the pipeline. The result is appended as a `role="tool"`
message and the provider is called again until a final answer is produced or
`max_tool_iterations` is reached. The default maximum is `4`.

Transparent client-provided tools (`tools` or `functions`) are preserved for
Cline/Continue unless `agent_hub.auto_execute_tools=true` is set.

## OpenAI Tool Schemas

Use `openai_tool_specs(registry)` to expose registered tools as
OpenAI-compatible `tools` entries. Tool calls can be normalized with
`ToolCall.from_openai(...)`.

## MCP Bridge

Configured MCP tool metadata is normalized into `Tool` objects with the same
permission pipeline. Full external MCP stdio/SSE execution is future-ready and
returns a clear unsupported result instead of pretending to run a server.
