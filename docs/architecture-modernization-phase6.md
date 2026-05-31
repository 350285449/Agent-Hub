# Agent-Hub Architecture Modernization Phase 6

Phase 6 modernizes workflow execution by separating deterministic workflow
planning and workflow event recording from `WorkflowEngine`. The engine still
executes the same stages in the same order, but stage policy, prompt shaping,
raw workflow metadata, review retry decisions, patch summaries, and workflow
event writes now live behind explicit workflow-layer boundaries.

## Summary of Changes

- Added `WorkflowPlanner` for deterministic workflow policy.
- Moved `WorkflowStage` into the workflow planning layer.
- Added `WorkflowEventRecorder` for workflow event sinks and JSONL events.
- Kept `WorkflowEngine.WORKFLOWS` stable through the planner contract.
- Kept workflow stage order and retry/validation/patch-summary behavior stable.
- Exported planner/event recorder types from `agent_hub.workflows`.

## Files Modified

- `agent_hub/workflows/planning.py`
- `agent_hub/workflows/events.py`
- `agent_hub/workflows/engine.py`
- `agent_hub/workflows/__init__.py`
- `tests/test_workflow_phase6.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase6.md`

## Architecture Boundary

Workflow execution now flows through three clearer pieces:

```text
WorkflowEngine
  -> WorkflowPlanner
       -> stage list, stage prompts, stage metadata, role mapping
       -> retry, validation, patch summary, file-touch policy
  -> WorkflowEventRecorder
       -> event sinks
       -> record_event("workflows", ...)
  -> AgentRouter
       -> provider execution
```

`WorkflowEngine` no longer imports `agent_hub.observability` directly.

## Compatibility Contract

Existing behavior remains stable:

- supported workflow names are unchanged
- default stages remain `plan`, `work`, `review`
- review-blocked code workflows still run one work/review retry when enabled
- validation commands and optional model validation remain unchanged
- patch summary metadata is still added when requested
- `raw["agent_hub"]["workflow"]` metadata shape is unchanged
- workflow events are still written to `workflow_execution.jsonl`

## Risks Introduced

- **Workflow prompt drift risk: medium.** Stage prompts moved to a planner. Direct
  planner tests assert prompt intent and workflow metadata.
- **Stage policy drift risk: medium.** Retry, validation, and patch-summary
  decisions moved with the planner. Existing workflow tests plus new planner
  tests cover these paths.
- **Observability drift risk: low.** Workflow event writing moved to a recorder.
  Tests assert sink events and JSONL workflow events.

## Validation Run

- `python -m unittest tests.test_workflow_phase6`
- `python -m unittest tests.test_phase1_phase2_foundation tests.test_phases_10_18`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest`

## Remaining Work

- Move validation command execution into a dedicated workflow tool runner.
- Add typed workflow plan/result contracts for future parallel or consensus
  workflow strategies.
- Keep workflow API response shaping out of execution code.

## Rollback Strategy

Move planner methods and event recorder calls back into `WorkflowEngine`, remove
`agent_hub/workflows/planning.py`, `agent_hub/workflows/events.py`, and
`tests/test_workflow_phase6.py`, then restore direct workflow event writes.
