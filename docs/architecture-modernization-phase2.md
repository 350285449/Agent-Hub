# Agent-Hub Architecture Modernization Phase 2

Phase 2 begins router decomposition by extracting preflight policy and
diagnostics builders out of `AgentRouter`. The router remains the public
compatibility facade and still owns request execution, failover, streaming, and
tool-loop orchestration.

## Summary of Changes

- Added `agent_hub.core.routing_policy.RouterPreflightPolicy`.
- Moved preflight eligibility checks for tool-capable requests, echo gating,
  `free_only`, missing API keys, quota metadata, and context-window sizing into
  the routing policy module.
- Moved public routing token helpers into the policy module while preserving
  imports from `agent_hub.core.router` and `agent_hub.router`.
- Added `agent_hub.core.router_diagnostics` for provider status rows and
  capability graph construction.
- Kept `AgentRouter.provider_status()`, `AgentRouter.capability_graph()`,
  `_preflight_skip_reason()`, and `_preflight_error_type()` as delegating
  compatibility methods.
- Updated router health and scoring paths to continue reading capabilities from
  the shared Phase 1.5 capability model.

## Files Modified

- `agent_hub/core/router.py`
- `agent_hub/core/routing_policy.py`
- `agent_hub/core/router_diagnostics.py`
- `tests/test_router_decomposition.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase2.md`

## Compatibility Contract

The following imports remain available from `agent_hub.router` and
`agent_hub.core.router`:

- `NO_TOOL_CAPABLE_MODEL`
- `ECHO_DISABLED`
- `CONFIGURATION_ERROR`
- `estimate_input_tokens`
- `expected_output_tokens`

Existing router methods remain available:

- `AgentRouter.route`
- `AgentRouter.stream`
- `AgentRouter.decide`
- `AgentRouter.recommend`
- `AgentRouter.health_snapshot`
- `AgentRouter.provider_status`
- `AgentRouter.capability_graph`

No endpoint response shape or provider execution behavior changed.

## Risks Introduced

- **Preflight ordering risk: medium.** Eligibility checks must keep their
  previous order because `free_only`, missing-key, tool-capability, quota, and
  context-window reasons affect client-facing failover messages. Focused tests
  now cover representative ordering and error classification.
- **Diagnostics drift risk: low.** Provider status and capability graph builders
  moved behind pure functions. Existing server and health tests cover the
  public shapes.
- **Import compatibility risk: low.** Public constants and token helper names
  are imported into the router facade, preserving legacy import paths.
- **Architecture guardrail risk: low.** The fan-out guardrail exempts only the
  new router-local extraction edges and continues rejecting cross-layer fan-out
  growth.

## Tests Added Or Updated

- Added focused routing policy tests for tool-capability preflight, quota
  metadata, missing API keys, and tool request detection.
- Added diagnostics builder tests for provider status rows and capability graph
  shape.
- Updated architecture guardrails for the two Phase 2 router extraction modules.

## Validation Run

- `python -m unittest tests.test_router_decomposition tests.test_architecture_guardrails`
- `python -m unittest tests.test_router tests.test_server tests.test_api_golden_fixtures`
- `python -m unittest tests.test_capabilities tests.test_architecture tests.test_phase8_packaging`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Extract router health snapshot assembly into a health diagnostics service.
- Extract failover event construction and cooldown handling from the execution
  loop.
- Extract streaming orchestration into a dedicated router streaming service.
- Move tool-loop orchestration behind the tool execution layer boundary.

## Rollback Strategy

Move the delegated policy and diagnostics logic back into `AgentRouter`, remove
the two extracted modules, and remove `tests/test_router_decomposition.py`.
Public imports and API fixtures require no rollback because their surface did
not change.
