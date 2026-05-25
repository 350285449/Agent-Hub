# Token Optimization

Agent Hub uses `TokenBudgetManager` modes:

- `minimal`
- `balanced`
- `deep`

The compactor reduces old, repeated, or low-signal context first. Protected
context is retained more aggressively:

- recent tool calls and tool results
- current task state
- TODO and `task_progress`
- active editor and open-file metadata
- workspace state
- MCP/tool state
- latest reasoning and assistant actions

Diagnostics expose incoming, compacted, protected, and dropped token counts via
`/debug/context`, `/debug/request`, and `agent-hub inspect-request`.
