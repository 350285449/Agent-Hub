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

Boost plans now add a soft target below the provider hard limit. When a request
is above that target, Agent Hub applies deterministic local algorithms before
sending the provider payload:

- semantic delta compaction collapses older near-duplicate tool results and logs
  while keeping the newest copy and unique high-signal lines
- extractive compaction turns noisy traceback, warning, diff, and repeated-output
  messages into short evidence digests
- budgeted context knapsack ranks older unprotected messages by utility per token
  and trims the lowest-value context first

Diagnostics expose incoming, compacted, protected, and dropped token counts via
`/debug/context`, `/debug/request`, and `agent-hub inspect-request`.

## Token Budget Ledger

`TokenBudgetLedger` records per-request or per-workflow stage budgets to
`.agent-hub/state/token_budget_ledger.jsonl`. Each row can include the stage,
workflow, role, planned/effective budget, actual or estimated input/output
tokens, and tokens saved. `/v1/usage` exposes a `token_budget_ledger` summary
with recent rows, totals, and counts by stage/workflow.

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
