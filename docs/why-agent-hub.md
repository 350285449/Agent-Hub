# Why Agent-Hub

Agent-Hub is a Claude Code and Codex optimizer for developer workspaces. It is
not only an AI gateway and not only a provider router. It classifies tasks,
understands repository context, assesses risk, ranks providers, executes with
failover, records outcomes, and uses that history to improve future routing.

## Positioning

Agent-Hub is the routing layer for reducing AI costs while preserving quality.
It routes each request automatically, then lets you verify the routing decision
locally.

Most AI gateways optimize the transport layer: keys, quotas, retries, logging,
and provider abstraction. Agent-Hub includes those gateway responsibilities, but
its differentiator is Adaptive Workspace Intelligence.

Agent-Hub answers:

- What kind of task is this?
- Which files, languages, frameworks, and repository signals matter?
- How risky is the request?
- Which workflow should run?
- Which provider/model is best for this task right now?
- Why were the other candidates rejected?
- What did prior outcomes teach the router?

## Local Proof In 30 Seconds

```text
Without Agent-Hub: $100/month
With Agent-Hub:    $66/month
Savings:           34%
```

Run the proof yourself:

```sh
agent-hub demo
agent-hub benchmark --dataset coding-100 --export results.json
agent-hub benchmark verify results.json --dataset coding-100
agent-hub benchmark compare results.json --dataset coding-100
agent-hub generate-proof
```

## Competitive Comparison

| Capability | Agent-Hub | OpenRouter | Cloudflare AI Gateway | Kong AI Gateway | LiteLLM | Portkey |
| --- | --- | --- | --- | --- | --- | --- |
| Multi-provider API routing | Yes | Yes | Yes | Yes | Yes | Yes |
| OpenAI-compatible gateway | Yes | Yes | Yes | Via gateway configuration | Yes | Yes |
| Provider health and failover | Yes | Partial | Yes | Yes | Yes | Yes |
| Cost/latency observability | Yes | Partial | Yes | Yes | Yes | Yes |
| Workspace-aware task classification | Yes | No | No | No | No | No |
| Repository/file/language intelligence | Yes | No | No | No | No | No |
| Risk-aware permission gates | Yes | No | No | Gateway policy only | No | Policy oriented |
| Workflow routing | Yes | No | No | No | No | Limited orchestration |
| Planner/worker/reviewer workflows | Yes | No | No | No | No | No |
| Adaptive learning from outcomes | Yes | No | No | No | Partial custom callbacks | Evaluation/observability oriented |
| Routing memory by task/repo pattern | Yes | No | No | No | No | No |
| Per-decision explanation object | Yes | Limited | Limited | Policy logs | Limited | Logs/traces |
| Local VS Code intelligence panel | Yes | No | No | No | No | No |
| Local-first workspace agent tools | Yes | No | No | No | No | No |

## Where Agent-Hub Wins

### Workspace Awareness

Agent-Hub classifies the request using task text, referenced files, file types,
language/framework hints, repository size, context size, and required
capabilities. That makes routing decisions specific to the workspace instead of
generic provider availability.

Key code:

- `agent_hub/core/task_classifier.py`
- `agent_hub/repository.py`
- `agent_hub/core/context_preparation.py`

### Adaptive Learning

Agent-Hub records outcome metadata and uses it to influence future routing.
Models that succeed on similar tasks can be boosted; models that time out or
fail on similar large-context tasks can be penalized.

Routing combines repository DNA, task type, language/framework, repo size,
context estimate, provider health, real success/failure history, latency, cost,
and user feedback. Cheap/free candidates can run first, low-confidence results
can escalate, and `tournament_mode` runs multiple worker candidates through a
judge before returning the selected result.

Key code:

- `agent_hub/adaptive.py`
- `agent_hub/routing_memory.py`
- `agent_hub/core/routing/selection.py`

### Workflow Routing

Agent-Hub can choose direct routing, single-worker, planned-worker,
reviewed-worker, and team-reviewed patterns. Workflow outcomes feed adaptive
analytics and future workflow upgrades.

Key code:

- `agent_hub/workflows/selector.py`
- `agent_hub/workflows/engine.py`
- `agent_hub/application/adaptive_service.py`

### Repository Intelligence

Agent-Hub can add compact repository context, preserve active file/task
signals, estimate context pressure, and route large repository work toward
models and workflows that can handle it.

Key code:

- `agent_hub/repository.py`
- `agent_hub/context.py`
- `agent_hub/token_optimizer.py`

### Explainability

Every routing decision now includes `RoutingDecisionExplanation`: selected
model, selected workflow, risk, reasons, rejected candidates, provider/model
rankings, adaptive signals, routing-memory signals, cost comparison, and
context optimization.

Surfaces:

- `GET /v1/routing-intelligence`
- `GET /dashboard/routing-intelligence`
- `GET /v1/routing/last-decision`
- `GET /v1/routing-decision/{request_id}`
- VS Code Routing Intelligence panel
- `GET /v1/model-leaderboard`
- `GET /v1/cost-dashboard`
- `GET /v1/benchmarks`

## When to Choose Agent-Hub

Choose Agent-Hub when you want a local orchestration layer for coding tools,
repository-aware agents, safety gates, workflows, adaptive learning, and
explainable routing.

Choose a pure gateway when you only need vendor abstraction, traffic logging, or
centralized key management and do not need workspace intelligence.
