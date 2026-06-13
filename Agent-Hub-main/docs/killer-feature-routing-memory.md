# Killer Feature: Self-Improving Routing Memory

Agent-Hub now records metadata-only routing outcomes and uses them to improve
future model/provider choices. The store lives at
`.agent-hub/state/routing_memory.jsonl` and is separate from full prompts,
session transcripts, and raw provider responses.

## What It Learns

- Task pattern: task type/category, language, framework, complexity, risk,
  repo-size bucket, context-size bucket, file types, and workflow hint.
- Provider outcome: agent, provider, model, latency, success/failure, retries,
  fallback count, timeout, permission denial, tool failure, reviewer failure,
  cancellation, cost estimate, and final outcome.
- Outcome score: a normalized score from `0.0` to `1.0` based on success,
  latency, fallback count, timeout, tool/reviewer failure, cancellation, and
  token efficiency when available.

## How It Changes Routing

For every candidate model, Agent-Hub finds similar past outcomes and computes a
memory signal. Strong similar history boosts the candidate. Repeated failures,
timeouts, or fallback-heavy outcomes penalize it. Similarity uses task category,
task type, language, framework, complexity, risk, repo size, context size, and
file-type overlap.

The dashboard and routing decision metadata show:

- original routing score
- memory adjustment
- final routing score
- similar outcomes used
- fallback candidates and why they lost
- selected provider/model/workflow and routing reasons

## API

```sh
curl http://127.0.0.1:8787/v1/routing-memory/stats
curl http://127.0.0.1:8787/v1/routing-memory/recent
curl http://127.0.0.1:8787/v1/routing-decision/hub-request-id
curl -X DELETE http://127.0.0.1:8787/v1/routing-memory
```

`/dashboard/optimization` includes successful models by task type,
failure-prone models, provider latency, fallback frequency, cost/performance
winner, and routing-memory influence per request.

## Config

```json
{
  "routing_memory_enabled": true,
  "routing_memory_store_prompts": false,
  "routing_memory_retention_days": 30
}
```

Environment fallbacks are also supported:

```sh
ROUTING_MEMORY_ENABLED=true
ROUTING_MEMORY_STORE_PROMPTS=false
ROUTING_MEMORY_RETENTION_DAYS=30
```
