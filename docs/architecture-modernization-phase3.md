# Agent-Hub Architecture Modernization Phase 3

Phase 3 moves provider tool-loop orchestration behind the tool execution layer.
The router still exposes the same methods and response metadata, but the loop
that validates tool calls, executes registered tools, records tool results, and
re-enters the provider now lives in `agent_hub.tools`.

## Summary of Changes

- Added `agent_hub.tools.orchestrator.ToolLoopRunner`.
- Added `ToolLoopRunResult` as the typed result of a tool-loop run.
- Moved tool-loop iteration mechanics out of `AgentRouter._run_tool_loop`.
- Kept `AgentRouter._run_tool_loop()` as a compatibility delegate.
- Kept `AgentRouter._should_execute_tool_calls()` as a compatibility delegate.
- Preserved tool-loop metadata shape under `raw["agent_hub"]`.
- Exported `ToolLoopRunner` and `ToolLoopRunResult` from `agent_hub.tools`.

## Files Modified

- `agent_hub/core/router.py`
- `agent_hub/tools/orchestrator.py`
- `agent_hub/tools/__init__.py`
- `tests/test_tool_runtime_phase3.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase3.md`

## Compatibility Contract

Existing router behavior remains stable:

- tool calls are auto-executed only for Agent-Hub-owned tool specs or explicit
  `auto_execute_tools` requests
- client-owned OpenAI `tools` / legacy `functions` remain client-owned
- duplicate tool-call loops stop with `tool_loop_max_reached`
- max tool iterations still use request overrides and config defaults
- tool-loop metadata still includes:
  - `tool_loop`
  - `tool_calls`
  - `tool_results`
  - `tool_iteration_count`

Existing public imports remain available from `agent_hub.tools`, with new
exports added for the extracted runtime boundary:

- `ToolLoopRunner`
- `ToolLoopRunResult`

## Risks Introduced

- **Tool-loop behavior risk: medium.** The loop is execution-sensitive because
  it controls provider re-entry, max-iteration stops, duplicate detection, and
  tool result metadata. Existing tool-loop tests and new direct runner tests
  cover these paths.
- **Client compatibility risk: medium.** OpenAI-compatible clients may provide
  their own tool specs. A focused test covers that those calls are not executed
  by Agent Hub unless they are Agent-Hub-owned.
- **Observability drift risk: low.** The extracted runner still calls back into
  the router's existing route-event recorder, preserving event names and fields.
- **Health drift risk: low.** The extracted runner still calls back into the
  router's tool-result health recorder.

## Tests Added Or Updated

- Added direct `ToolLoopRunner` coverage for a successful tool execution and
  provider re-entry.
- Added direct coverage that client-owned tool specs are left for the client.
- Updated public import guardrails for `ToolLoopRunner`.

## Validation Run

- `python -m unittest tests.test_tool_runtime_phase3`
- `python -m unittest tests.test_phases_10_18 tests.test_phase6_10 tests.test_resilience`
- `python -m unittest tests.test_architecture_guardrails tests.test_router`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Unify legacy `agent_hub.agent_tools.AgentToolbox` with the typed tool
  registry where possible.
- Extract shell/filesystem checkpoint policy from `agent_tools.py`.
- Move tool permission event recording fully behind the tool permission layer.
- Continue reducing direct router ownership of tool-loop response shaping.

## Rollback Strategy

Move the loop body from `ToolLoopRunner.run()` back into
`AgentRouter._run_tool_loop()`, remove `agent_hub/tools/orchestrator.py`, and
remove `tests/test_tool_runtime_phase3.py`. No API fixture rollback is required.
