# Workflows

Workflows are deterministic, practical orchestration paths. They are not
recursive autonomous agents.

## Stages

Every workflow uses explicit stages:

1. Planner: produces a concise plan, likely files, risks, and validation.
2. Worker: executes or explains the task depending on workflow type.
3. Reviewer: checks correctness, safety, regressions, and missing tests.

Optional stages:

- Worker retry and reviewer retry run once when the latest review contains a
  blocking issue.
- Test stage runs configured `validation_commands` through `shell_execute` when
  shell tools are allowed.
- Validator stage runs when `validate=true` or validation commands are present.
- Patch summary stage runs when `patch_summary=true`.

Execution controls:

- `agent_hub.workflow_stage_timeout_seconds` sets a per-stage timeout.
- `agent_hub.workflow_cancelled=true` cancels before the next stage starts.
- `agent_hub.dry_run=true` previews workflow-owned file and shell actions
  through the workspace service without applying file modifications.
- Validation commands use `SafeWorkspaceService`, so shell policy, permission
  checks, audit logs, and dry-run behavior match normal tools.

Initial workflow endpoints:

- `POST /v1/workflows/code`
- `POST /v1/workflows/review`
- `POST /v1/workflows/debug`
- `POST /v1/workflows/explain`
- `POST /v1/workflows/refactor`
- `POST /v1/auto`

`POST /v1/auto` selects a workflow pattern automatically:

- `direct_route` for small general requests.
- `single_worker` for small coding/tool tasks.
- `planned_worker` for normal coding/debug work.
- `reviewed_worker` for critical, review, security, or multi-file tasks.
- `team_reviewed` for large, high-risk, architecture, or migration tasks.

Large `team_reviewed` tasks run planner and researcher stages, then fan out
non-editing worker proposals, choose the best proposal with a judge step, and
only then run the editing worker once. This keeps the large-task workflow
competitive without allowing multiple workers to edit the same workspace at the
same time.

## Routing Preferences

Planner stages prefer reasoning. Coder/refactor/debug stages prefer coding
routes. Reviewer stages prefer reliable providers. `group_roles` can pin a
role to a configured agent.

## Memory

Workflow memory records stage outputs, agents, models, failover, timings, and
progress metadata. The next stage receives prior stage summaries in prompt
context, making execution explainable and repeatable.

The workflow state records `stages`, `retries`, `files_touched`,
`validation_result`, and `final_status`.

Adaptive workflow analytics aggregate each selected pattern by task type. The
optimization dashboard shows success rate, average cost, average latency,
average retries, recovered failovers, and the strongest planner/worker models
for each workflow-task row.

Workflow execution events are written to
`.agent-hub/state/workflow_execution.jsonl` and surfaced by
`GET /v1/workflows/status`. Passive extension-point models are available for
planner/reviewer roles, parallel provider calls, consensus/voting, and result
merging; they are SDK foundation objects and do not change deterministic
workflow execution yet.

Adaptive workflow upgrades are enabled by default. Set
`adaptive_workflow_upgrades_enabled=false` to keep selector decisions purely
heuristic while still recording workflow analytics.
