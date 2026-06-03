# Adaptive Workspace Intelligence™

Adaptive Workspace Intelligence™ is Agent-Hub's flagship capability: the hub
does not only proxy model calls, it understands the request, the workspace, the
risk profile, the available providers, and prior outcomes before it chooses how
to respond.

## Architecture

```text
User Request
  |
  v
Task Classification
  |
  v
Workspace Analysis
  |
  v
Risk Assessment
  |
  v
Workflow Selection
  |
  v
Provider Selection
  |
  v
Execution
  |
  v
Outcome Analysis
  |
  v
Adaptive Learning
  |
  v
Future Routing Improvement
```

The important design rule is that Agent-Hub does not duplicate routing systems
to create this product feature. It exposes the intelligence already present in
the router, task classifier, workflow selector, health tracker, routing memory,
and adaptive learning store.

## Code Map

| Stage | Existing code | Responsibility |
| --- | --- | --- |
| User Request | `agent_hub/payloads.py`, `agent_hub/api/compatibility.py` | Normalize OpenAI, Anthropic, Responses, and native payloads into `HubRequest`. |
| Task Classification | `agent_hub/core/task_classifier.py` | Detect task type, category, language, framework, complexity, context size, required capabilities, and risk. |
| Workspace Analysis | `agent_hub/repository.py`, `agent_hub/core/context_preparation.py`, `agent_hub/context.py` | Inject repository context, estimate tokens, preserve protected context, and choose context strategy. |
| Risk Assessment | `agent_hub/core/task_classifier.py`, `agent_hub/security/provider_permissions.py`, `agent_hub/permissions.py` | Identify shell, file-write, config, provider, and security-sensitive actions. |
| Workflow Selection | `agent_hub/workflows/selector.py`, `agent_hub/application/adaptive_service.py` | Choose direct, single-worker, planned, reviewed, or team-reviewed execution. |
| Provider Selection | `agent_hub/core/routing/selection.py`, `agent_hub/core/health.py` | Rank provider/model candidates using route, health, capabilities, cost, adaptive learning, and routing memory. |
| Execution | `agent_hub/core/provider_attempts.py`, `agent_hub/providers/*`, `agent_hub/tools/*` | Call providers, run tool loops, continue after output limits, and fail over when needed. |
| Outcome Analysis | `agent_hub/core/routing/selection.py`, `agent_hub/observability.py` | Record success/failure, latency, tokens, cost, failovers, provider health, and events. |
| Adaptive Learning | `agent_hub/adaptive.py`, `agent_hub/routing_memory.py` | Persist metadata-only outcomes and compute future route/workflow/model influence. |
| Future Improvement | `agent_hub/core/routing/selection.py`, `agent_hub/workflows/selector.py` | Apply adaptive bonuses, routing-memory adjustments, reviewer gates, and workflow upgrades. |

## Routing Lifecycle

1. A client sends a request to `/v1/chat/completions`, `/v1/messages`,
   `/v1/responses`, `/v1/agent`, `/v1/auto`, or a workflow endpoint.
2. Agent-Hub normalizes the request into `HubRequest`.
3. `TaskClassifier.classify()` identifies the task and workspace signals.
4. `WorkflowSelector.select()` chooses a workflow when auto/workflow mode is
   used.
5. `AgentRouter.decide()` builds a ranked fallback chain and candidate
   scorecards.
6. `ProviderAttemptExecutor.execute()` applies preflight checks, permissions,
   provider calls, output-limit continuation, and failover.
7. The response records `RoutingDecisionExplanation` in routing logs and, when
   enabled, response metadata.

## Learning Lifecycle

1. Provider success/failure updates `.agent-hub/state/provider_health.json`.
2. Routing outcomes are recorded in `.agent-hub/state/routing_memory.jsonl`.
3. Adaptive aggregates are stored in
   `.agent-hub/state/adaptive_learning.json`.
4. Workflow outcomes update workflow-pattern and role-level aggregates.
5. Future candidate scoring reads adaptive bonuses and routing-memory
   adjustments.
6. `/v1/optimization` and `/v1/routing-intelligence` expose learned model,
   provider, workflow, cost, latency, retry, and success-rate trends.

## Examples

### Simple explanation

Input:

```text
Explain what this function does.
```

Likely signals:

- `task_type=simple_explanation`
- `routing_mode=cheapest`
- Low risk
- Standard context strategy

Outcome:

- A cheaper fast model can win if available and healthy.
- The explanation object shows the selected model and why larger coding models
  were ranked lower.

### Large TypeScript refactor

Input:

```text
Refactor src/App.tsx and src/state.ts in this React repo.
```

Likely signals:

- `task_type=coding`
- `task_category=refactor`
- `language=typescript`
- `framework=react`
- `complexity=high`
- `repository_context_needed=true`
- `workflow_hint=planner_coder_reviewer`

Outcome:

- Long-context, tool-capable coding models rank higher.
- Routing memory can boost models that previously succeeded on similar
  TypeScript refactors.
- The dashboard shows selected workflow, provider rankings, rejected
  candidates, context estimates, and adaptive signals.

### Risky config or shell change

Input:

```text
Update config and run the install command.
```

Likely signals:

- `risk_level=high`
- `permission_requirements=config_write_review,shell_command`
- Review and permission gates remain active

Outcome:

- Providers may be blocked until policy approves the external call.
- Workflow selection favors review-capable paths.
- Permission events and routing explanations are visible in the dashboard and
  VS Code panel.

## Product Surfaces

- API: `GET /v1/routing-intelligence`
- Dashboard: `GET /dashboard/routing-intelligence`
- Existing optimization view: `GET /dashboard/optimization`
- Last decision lookup: `GET /v1/routing/last-decision`
- Request decision lookup: `GET /v1/routing-decision/{request_id}`
- Routing history: `GET /v1/routing-history`
- VS Code: Routing Intelligence sidebar panel

## Explanation Schema

Every `RoutingDecision` now includes an `explanation` object:

```json
{
  "object": "agent_hub.routing_decision_explanation",
  "summary": "Selected openai-compatible/tool-model: Selected best available candidate for coding task.",
  "selected": {
    "agent": "tooly",
    "provider": "openai-compatible",
    "model": "tool-model",
    "workflow": "planner_coder_reviewer",
    "routing_mode": "coding",
    "task_type": "coding",
    "risk_level": "medium"
  },
  "reasons": [
    {
      "label": "Task classification",
      "detail": "coding / refactor / high",
      "source": "TaskClassifier"
    }
  ],
  "rejected": [
    {
      "agent": "mini",
      "provider": "openai",
      "model": "gpt-mini",
      "reason": "Lower final routing score."
    }
  ]
}
```

The explanation is derived from current routing scorecards, not from a separate
post-hoc rules engine.
