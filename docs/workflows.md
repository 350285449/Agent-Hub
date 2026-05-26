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

Initial workflow endpoints:

- `POST /v1/workflows/code`
- `POST /v1/workflows/review`
- `POST /v1/workflows/debug`
- `POST /v1/workflows/explain`
- `POST /v1/workflows/refactor`

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

Workflow execution events are written to
`.agent-hub/state/workflow_execution.jsonl` and surfaced by
`GET /v1/workflows/status`. Passive extension-point models are available for
planner/reviewer roles, parallel provider calls, consensus/voting, and result
merging; they are SDK foundation objects and do not change deterministic
workflow execution yet.
