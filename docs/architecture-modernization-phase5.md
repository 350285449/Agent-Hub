# Agent-Hub Architecture Modernization Phase 5

Phase 5 starts observability modernization by moving router event shaping behind
a dedicated event recorder. The router still emits the same routing and internal
event streams, but it no longer writes raw observability events directly or owns
request source extraction.

## Summary of Changes

- Added `RouterEventRecorder` to the observability/event layer.
- Added `request_event_context()` for stable router event request metadata.
- Added `request_source()` as the shared source extraction helper.
- Moved routing JSONL event payload shaping out of `AgentRouter`.
- Moved internal router event request-context shaping out of `AgentRouter`.
- Kept `AgentRouter._record_route_event()` as a compatibility delegate.
- Kept `AgentRouter._record_internal_event()` as a compatibility delegate.
- Preserved existing stream names, event names, and request metadata fields.

## Files Modified

- `agent_hub/events.py`
- `agent_hub/core/router.py`
- `tests/test_observability_phase5.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase5.md`

## Architecture Boundary

Router observability now flows through one boundary:

```text
AgentRouter
  -> RouterEventRecorder
       -> record_event("routing", ...)
       -> record_internal_event(...)
            -> record_event("events", ...)
```

The router no longer imports `agent_hub.observability` directly.

## Compatibility Contract

Existing behavior remains stable:

- routing events are still written to `routing_decisions.jsonl`
- internal events are still written to `events.jsonl`
- event names such as `provider.selected`, `provider.failed`,
  `router.fallback`, `stream.started`, and `stream.failed` are unchanged
- request metadata still includes:
  - `request_id`
  - `session_id`
  - `route`
  - `preferred_agent`
  - `api_shape`
  - `source`
- provider health still records the same last request source value
- tool-loop callbacks can keep using `AgentRouter._record_route_event()`

## Risks Introduced

- **Diagnostics drift risk: medium.** Dashboard and extension diagnostics depend
  on event stream names and fields. Direct tests assert the routing and internal
  event shapes.
- **Source attribution risk: low.** Request source extraction moved from the
  router to the event layer. A focused test preserves the previous priority:
  metadata, raw request, Agent Hub options, then API shape.
- **Private extension risk: low.** Router event helper methods remain as
  compatibility delegates.
- **Import-boundary risk: low.** Architecture guardrails now assert the router
  depends on `agent_hub.events` rather than raw `agent_hub.observability`.

## Tests Added Or Updated

- Added direct `RouterEventRecorder` coverage for routing event shape.
- Added direct coverage for internal event context and nested field sanitization.
- Added request-source priority coverage.
- Added architecture guardrail coverage for the router observability boundary.

## Validation Run

- `python -m unittest tests.test_observability_phase5`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest tests.test_phase1_phase2_foundation tests.test_router tests.test_server`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Move provider health event derivation behind an observability/health recorder.
- Move server dashboard metrics assembly behind a diagnostics facade.
- Consolidate permission, security, enterprise, tool, and workflow event readers
  behind stable observability query objects.

## Rollback Strategy

Move `RouterEventRecorder.route()` and `RouterEventRecorder.internal()` bodies
back into `AgentRouter._record_route_event()` and
`AgentRouter._record_internal_event()`, restore the router's direct
`agent_hub.observability.record_event` import, and remove
`tests/test_observability_phase5.py`.
