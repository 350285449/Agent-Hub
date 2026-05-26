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

Additional Phase 2 options:

```json
{
  "context_cache_enabled": true,
  "context_cache_max_entries": 128,
  "context_summarization_enabled": false
}
```

The cache stores reusable token-estimate metadata in
`.agent-hub/state/context_cache.json`. It does not store API keys and does not
change request text by itself. `context_summarization_enabled` is a hook point
for future or plugin-provided summarizers; without a hook, Agent Hub keeps using
safe truncation and protected-context preservation.
