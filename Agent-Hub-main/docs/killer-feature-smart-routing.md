# Killer Feature: Smart Workspace-Aware Model Routing

Agent-Hub routes by more than provider health or price. It inspects the task,
repository context hints, repository size, file types, programming
language/framework, context size, risk level, expected cost, permissions, review
needs, and required capabilities before choosing a provider/model/workflow.

The implementation lives in:

- `agent_hub.core.task_classifier.TaskClassifier`
- `agent_hub.core.context_preparation.ContextPreparationService`
- `agent_hub.core.routing.selection.AgentRouter.decide`
- `/v1/routing/last-decision`, `/v1/routing/status`, `/v1/status`

## What It Looks At

- Task type/category: general, explanation, code generation, refactor,
  debugging, test generation, documentation, shell/tool operation, large-context
  repository task, local/private, or security-sensitive operation.
- Language/framework: file extensions, active files, and package/config hints.
- Repository size: workspace scan or request metadata bucket.
- File types: code, docs, config, dependency files, lockfiles, and environment
  files.
- Complexity: low, medium, or high from task type, risk, file count, context,
  and repo-size bucket.
- Risk: file writes, deletes, config edits, installs, shell commands, secrets,
  and high-risk destructive patterns.
- Expected cost: low, medium, or high from context size, complexity, and repo
  size.
- Reviewer need: high-risk edits, multi-file writes, and risky shell/file tasks.
- Permission requirements: tool execution, shell command, file write,
  config-write review, and security review.
- Capabilities: coding score, reasoning score, speed, tool support, streaming,
  context window, cost metadata, provider health, and quota state.
- Repository need: whether repo-map injection or context compression should be
  used before provider execution.

## Examples

- Simple explanation: choose a cheaper fast candidate when available.
- Large refactor: choose a long-context coding candidate and enable repo/context
  strategy metadata.
- Security-sensitive file operation: choose the coding/reviewer path and keep
  permission gates active.
- Failed provider: mark cooldown/health, record fallback, and try the next
  compatible candidate.
- Large repo task: compress context and inject repository map evidence.
- High-risk shell command: block or require approval through the central
  permission manager.

## Demo

```sh
curl http://127.0.0.1:8787/v1/routing/last-decision
```

Look for:

- `selected_provider`
- `selected_model`
- `selected_workflow`
- `candidate_scores[].original_routing_score`
- `candidate_scores[].memory_adjustment`
- `candidate_scores[].final_routing_score`
- `routing_reason`
- `task_classification`
- `permission_requirements`
- `cost_context_estimate`
- `failover`

To preview a decision without calling a provider:

```sh
curl -X POST http://127.0.0.1:8787/v1/routing/simulate \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Refactor the auth module and update tests"}]}'
```

## Tests

Focused coverage lives in `tests/test_smart_workspace_routing.py`:

- task classification
- smart routing decisions
- context preparation outside router decision
- no internal metadata leak in compatibility responses
- workflow timeout/cancellation
- dry-run workspace actions
- concurrent request health updates
