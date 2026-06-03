# Agent-Hub Routing Intelligence Architecture Audit

This report maps the existing systems that already make Agent-Hub intelligent.
The implementation work should expose and explain these systems, not replace
them.

## 1. Existing Routing Systems

Locations:

- `agent_hub/core/routing/selection.py`
- `agent_hub/core/routing_policy.py`
- `agent_hub/core/provider_attempts.py`
- `agent_hub/config.py`
- `agent_hub/payloads.py`

Responsibilities:

- Classify requests, resolve routes, rank candidate agents, and build fallback
  chains.
- Apply routing modes such as `best_available`, `coding`, `long_context`,
  `fastest`, `cheapest`, and `local_private`.
- Execute provider attempts with preflight skips, permission checks, cooldowns,
  output-limit continuation, and retry/failover behavior.

Strengths:

- Routing is already workspace-aware, health-aware, quota-aware, and capability
  aware.
- Fallback is a first-class execution path, not a dashboard-only concept.
- Candidate scorecards already include health, adaptive, cost, capability, and
  routing-memory signals.

Missing Visibility:

- The raw `RoutingDecision` object was detailed but not shaped as a product
  explanation.
- Users had to inspect JSON or logs to understand rejected candidates.
- Dashboard naming emphasized optimization, not decision intelligence.

## 2. Existing Adaptive Learning Systems

Locations:

- `agent_hub/adaptive.py`
- `agent_hub/application/adaptive_service.py`
- `agent_hub/core/routing/selection.py`
- `.agent-hub/state/adaptive_learning.json`
- `.agent-hub/state/adaptive_learning_events.jsonl`

Responsibilities:

- Persist outcome aggregates by exact route/task/workflow/role, task, and
  global model scope.
- Score adaptive routing bonuses after sample thresholds are met.
- Track workflow success, retries, latency, cost, and feedback.
- Summarize model win rates, provider effectiveness, workflow analytics, and
  dashboard recommendations.

Strengths:

- Adaptive data is compact and metadata-oriented.
- Learning is already integrated into routing and workflow selection.
- The service boundary already exposes `/v1/optimization` and
  `/v1/routing/simulate`.

Missing Visibility:

- Adaptive influence was present in candidate scorecards but not promoted as a
  flagship capability.
- Users could not easily see how adaptive samples affected a single decision.

## 3. Existing Workflow Learning Systems

Locations:

- `agent_hub/workflows/selector.py`
- `agent_hub/workflows/engine.py`
- `agent_hub/application/adaptive_service.py`
- `agent_hub/adaptive.py`
- `.agent-hub/state/workflow_execution.jsonl`

Responsibilities:

- Select direct, single-worker, planned-worker, reviewed-worker, and
  team-reviewed patterns.
- Upgrade workflows when historical task data shows a better pattern.
- Record workflow success, retries, latency, cost, and failover recovery.

Strengths:

- Workflow selection is deterministic, explainable, and connected to adaptive
  outcomes.
- Role-level winners identify effective planner, worker, coder, and reviewer
  providers.

Missing Visibility:

- Workflow analytics existed mostly inside the optimization dashboard.
- Users needed a clearer "which workflow should I trust for this task?" view.

## 4. Existing Scoring Systems

Locations:

- `agent_hub/core/health.py`
- `agent_hub/core/routing/selection.py`
- `agent_hub/routing_memory.py`
- `agent_hub/evaluation/__init__.py`
- `.agent-hub/state/provider_health.json`
- `.agent-hub/state/provider_scores.json`

Responsibilities:

- Score provider reliability, latency, streaming speed, quota, and tool-call
  health.
- Score candidate routing fit using priority, task type, capabilities, health,
  adaptive learning, routing memory, cost efficiency, and benchmark scores.
- Persist benchmark scores and use them as routing bias.

Strengths:

- Scoring is multi-factor and already normalized into candidate scorecards.
- Health and benchmark stores are reusable by dashboards and APIs.

Missing Visibility:

- Provider and model ranking tables existed in pieces but were not consolidated
  around a single routing decision.

## 5. Existing Telemetry Systems

Locations:

- `agent_hub/observability.py`
- `agent_hub/events.py`
- `agent_hub/routing_diagnostics.py`
- `.agent-hub/state/routing_decisions.jsonl`
- `.agent-hub/state/request_trace.jsonl`
- `.agent-hub/state/events.jsonl`
- `.agent-hub/state/permission_audit.jsonl`
- `.agent-hub/state/tool_execution_history.jsonl`

Responsibilities:

- Record routing decisions, provider failures, fallback events, request traces,
  permission events, tool executions, workflow events, and adaptive events.
- Provide recent event snapshots for diagnostics APIs and dashboards.

Strengths:

- Telemetry is local, auditable, and already split by concern.
- Existing diagnostics endpoints can expose the same records without a new
  persistence system.

Missing Visibility:

- Event streams were machine-readable but not organized into a single
  intelligence narrative.

## 6. Existing Dashboard Systems

Locations:

- `agent_hub/server.py`
- `agent_hub/server_routes/config.py`
- `agent_hub/server_routes/diagnostics.py`
- `vscode-extension/extension.js`

Responsibilities:

- Render `/dashboard` and `/dashboard/optimization`.
- Expose VS Code sidebar health, setup, models, limits, tokens, activity, and
  permission state.
- Show optimization tables for model winners, workflow analytics, routing
  memory, provider effectiveness, and adaptive decisions.

Strengths:

- No frontend build pipeline is required.
- Dashboard data already comes from stable JSON APIs.
- VS Code can reuse backend diagnostics directly.

Missing Visibility:

- No dedicated "Routing Intelligence" page or sidebar section existed.
- Dashboard language did not make the product's intelligence obvious.

## 7. Existing Explainability Systems

Locations:

- `agent_hub/core/routing/selection.py`
- `agent_hub/routing_diagnostics.py`
- `docs/routing-decision-explainability.md`
- `docs/api.md`

Responsibilities:

- Build `RoutingDecision` with classification, selected provider/model,
  routing reasons, fallback candidates, fallback rejections, candidate scores,
  memory adjustments, and cost/context estimates.
- Expose decision lookup through `/v1/routing/last-decision`,
  `/v1/routing-decision/{request_id}`, `/v1/status`, and routing history.

Strengths:

- Explainability already follows the real router path.
- Decision lookup accepts OpenAI-compatible response IDs.

Missing Visibility:

- The explanation needed a stable product-facing schema.
- Dashboard and VS Code needed to render reasons, rejected candidates, risk,
  workflow, repository analysis, and fallback options directly.

## Implementation Direction

The current implementation adds `RoutingDecisionExplanation`, the
`/v1/routing-intelligence` API, `/dashboard/routing-intelligence`, a VS Code
Routing Intelligence panel, and benchmark-suite tooling. All of these compose
existing router, health, adaptive, routing-memory, workflow, and telemetry
systems.
