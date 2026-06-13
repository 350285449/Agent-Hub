# Agent-Hub Architecture Modernization Phase 8

Phase 8 continues API compatibility extraction by moving model catalog
construction and compatibility response-header shaping out of `server.py`.
The HTTP handler still owns transport concerns, but OpenAI model-list rows,
available model IDs, standard response headers, stream response headers, and
header sanitization now live in `agent_hub.api.compatibility`.

## Summary of Changes

- Moved model catalog row construction into the API compatibility layer.
- Moved OpenAI `/v1/models` row shaping into the API compatibility layer.
- Moved available model ID derivation into the API compatibility layer.
- Moved response and stream compatibility header construction into the API
  compatibility layer.
- Moved response token metadata and permission-status header policy into the API
  compatibility layer.
- Kept private server delegates for existing tests and internal callers.

## Files Modified

- `agent_hub/api/compatibility.py`
- `agent_hub/server.py`
- `tests/test_api_compatibility_phase8.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase8.md`

## Architecture Boundary

Compatibility output shaping now flows through one API layer:

```text
AgentHubHandler
  -> api.compatibility.model_rows(...)
  -> api.compatibility.openai_model_rows(...)
  -> api.compatibility.available_model_ids(...)
  -> api.compatibility.response_headers(...)
  -> api.compatibility.stream_response_headers(...)
```

`server.py` keeps `_model_rows()`, `_openai_model_rows()`,
`_response_headers()`, and `_stream_response_headers()` as compatibility
delegates only.

## Compatibility Contract

Existing behavior remains stable:

- `/v1/models`, `/models`, and `/api/v1/models` keep the same response shape
- route aliases such as `agent-hub-coding` remain listed
- agent aliases such as `agent:<name>` remain listed
- OpenAI model rows omit Agent Hub metadata unless routing details are requested
- provider, model, failover, quota, permission, safe-mode, and context warning
  headers keep the same names and values
- native stream compatibility headers keep the same names and values

## Risks Introduced

- **Model-list drift risk: medium.** IDE clients use model lists for routing.
  Direct Phase 8 tests and golden API fixtures cover row shape and aliases.
- **Header drift risk: medium.** Clients read compatibility headers for active
  model, failover, limits, and permission status. Direct tests cover response
  and stream headers.
- **Private compatibility risk: low.** Server private helpers remain as
  delegates to the API layer.

## Validation Run

- `python -m unittest tests.test_api_compatibility_phase8`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest tests.test_server tests.test_api_golden_fixtures tests.test_api_compatibility_phase7`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Move SSE event emission for OpenAI, Anthropic, and native streams behind
  dedicated API emitters.
- Split diagnostic endpoint body assembly out of `server.py`.
- Keep reducing server dependencies until it becomes transport orchestration
  rather than compatibility-policy owner.

## Rollback Strategy

Move model catalog and response-header functions back into `server.py`, restore
direct private helper bodies, and remove `tests/test_api_compatibility_phase8.py`.
