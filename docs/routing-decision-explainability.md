# Routing Decision Explainability

Agent-Hub returns structured routing metadata when `expose_routing_details` is
enabled and always records compact routing events in
`.agent-hub/state/routing_decisions.jsonl`.

## Decision Object

The routing decision includes:

- `task_type`, `task_category`, `language`, `framework`, `complexity`, `risk`,
  and `context_estimate`
- `selected_provider`, `selected_model`, `selected_workflow`, and
  `fallback_candidates`
- `routing_reasons`, `permission_requirements`, and `task_classification`
- `candidate_scores`, each with `original_routing_score`,
  `memory_adjustment`, `final_routing_score`, adaptive-learning signal,
  routing-memory signal, health, cost, and capabilities
- `fallback_rejections`, explaining why lower-ranked candidates lost
- `memory_adjustments`, summarizing the memory influence that affected ranking

Example:

```json
{
  "task_type": "coding",
  "task_category": "refactor",
  "language": "typescript",
  "framework": "react",
  "complexity": "high",
  "risk": "medium",
  "context_estimate": "large",
  "selected_provider": "anthropic",
  "selected_model": "claude-sonnet",
  "selected_workflow": "planner_coder_reviewer",
  "routing_reasons": [
    "Prompt was classified as coding-related and ranked by coding/tool capability.",
    "Routing memory boosted claude by +4.10 from 8 similar sample(s), 92% success."
  ]
}
```

## Lookup

```sh
curl http://127.0.0.1:8787/v1/routing/last-decision
curl http://127.0.0.1:8787/v1/routing-decision/hub-request-id
curl http://127.0.0.1:8787/v1/status
```

OpenAI-compatible response IDs such as `chatcmpl-hub-...` are accepted by the
decision lookup endpoint and mapped back to the underlying `hub-...` request ID.
