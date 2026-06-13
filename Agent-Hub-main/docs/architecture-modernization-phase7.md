# Agent-Hub Architecture Modernization Phase 7

Phase 7 starts API compatibility layer extraction by moving compatibility
endpoint dispatch, request metadata enrichment, model alias routing, model
lookup errors, and response shape selection out of `server.py`. The HTTP server
still owns sockets, headers, and SSE emission, but OpenAI/Anthropic/native
compatibility semantics now live under `agent_hub.api`.

## Summary of Changes

- Added `agent_hub.api.compatibility`.
- Added `CompatibilityEndpoint` and a POST endpoint registry.
- Moved header-to-request metadata enrichment into the API compatibility layer.
- Moved internal client compatibility metadata attachment out of `server.py`.
- Moved model alias routing and model lookup errors into the API layer.
- Moved non-streaming response shape selection into the API layer.
- Re-exported compatibility stream helpers from the API layer.
- Kept private server delegates for existing tests and compatibility imports.

## Files Modified

- `agent_hub/api/compatibility.py`
- `agent_hub/server.py`
- `tests/test_api_compatibility_phase7.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase7.md`

## Architecture Boundary

HTTP handling now delegates compatibility semantics:

```text
AgentHubHandler
  -> api.compatibility.compatibility_endpoint(path)
  -> api.compatibility.request_from_compat_payload(...)
  -> api.compatibility.apply_model_routing(...)
  -> api.compatibility.model_lookup_error(...)
  -> api.compatibility.response_for_shape(...)
  -> AgentRouter / AgentRunner / TeamAgentRunner
```

`server.py` no longer imports `agent_hub.payloads` directly.

## Compatibility Contract

Existing behavior remains stable:

- `/agent`, `/v1/agent`, `/v1/route`, `/v1/chat/completions`,
  `/api/v1/chat/completions`, `/openrouter/v1/chat/completions`,
  `/v1/responses`, and `/v1/messages` remain registered
- OpenAI chat, OpenAI Responses, Anthropic Messages, and native response shapes
  are unchanged
- session headers, user-agent client detection, and Cline compatibility metadata
  are unchanged
- model alias routing and unknown `agent:*` lookup errors are unchanged
- `/v1/models` output remains stable

## Risks Introduced

- **API drift risk: medium.** Compatibility endpoints are consumed by external
  IDE clients. Golden fixture tests and endpoint guardrails cover response
  shapes and path registration.
- **Client metadata drift risk: medium.** Header/session/client detection moved
  to a new module. Direct tests cover session headers and Cline metadata.
- **Model alias drift risk: low.** Model routing moved to the API layer while
  server private delegates remain available for existing callers.
- **Server import drift risk: low.** Guardrails assert server now depends on the
  API compatibility layer instead of raw payload helpers.

## Validation Run

- `python -m unittest tests.test_api_compatibility_phase7`
- `python -m unittest tests.test_api_golden_fixtures tests.test_server`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Move SSE formatting for native/OpenAI/Anthropic streams behind API compatibility
  response emitters.
- Move model-list construction out of `server.py` while preserving private
  compatibility delegates.
- Split diagnostics endpoints from compatibility endpoints in the HTTP handler.

## Rollback Strategy

Move request metadata, endpoint dispatch, model routing, lookup errors, and
response shape selection back into `server.py`, restore direct payload imports,
and remove `agent_hub/api/compatibility.py` and
`tests/test_api_compatibility_phase7.py`.
