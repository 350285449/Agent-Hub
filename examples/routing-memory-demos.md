# Routing Memory Demo Examples

These examples assume Agent-Hub is running on `127.0.0.1:8787`.

## Simple Explanation Routed Cheaply

```sh
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"agent-hub","messages":[{"role":"user","content":"Explain what a context window is."}],"agent_hub":{"routing_mode":"cheapest"}}'
```

## Large Refactor Routed To A Strong Coding Model

```sh
curl http://127.0.0.1:8787/v1/routing/simulate \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Refactor the large TypeScript workspace across src/App.tsx and src/routes/index.tsx."}]}'
```

## Risky Shell/File Task Routed Through Review

```sh
curl http://127.0.0.1:8787/v1/routing/simulate \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Edit agent-hub.config.json and run npm install."}]}'
```

Look for `selected_workflow`, `permission_requirements`, and `reviewer_required`
in the routing decision.

## Failed Provider Falling Back

Use a route where the first provider is intentionally unavailable, then send:

```sh
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"agent-hub-coding","messages":[{"role":"user","content":"Fix src/app.py"}]}'
```

Then inspect:

```sh
curl http://127.0.0.1:8787/v1/routing/last-decision
curl http://127.0.0.1:8787/v1/routing-memory/recent
```

## Memory Improving Future Routing

After repeated successful outcomes for one model and repeated failures for
another on similar tasks, inspect the influence:

```sh
curl http://127.0.0.1:8787/v1/routing-memory/stats
curl http://127.0.0.1:8787/dashboard/optimization
```

Future routing decisions will show `original_routing_score`,
`memory_adjustment`, and `final_routing_score` for each candidate.
