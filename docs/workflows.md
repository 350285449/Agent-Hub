# Workflows

Workflows are deterministic, practical orchestration paths. They are not
recursive autonomous agents.

## Stages

Every workflow uses explicit stages:

1. Planner: produces a concise plan, likely files, risks, and validation.
2. Worker: executes or explains the task depending on workflow type.
3. Reviewer: checks correctness, safety, regressions, and missing tests.

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
