# Agent-Hub Architecture Modernization Phase 9

Phase 9 moves compatibility SSE frame formatting into the API compatibility
layer. The HTTP server still owns sockets, common headers, and client disconnect
handling, but OpenAI Chat, OpenAI Responses, and Anthropic Messages stream frame
construction now lives under `agent_hub.api.compatibility`.

## Summary of Changes

- Added `openai_chat_sse_frames()`.
- Added `openai_response_sse_frames()`.
- Added `anthropic_sse_frames()`.
- Added low-level `sse_data_frame()` and `sse_named_event_frame()` helpers.
- Replaced server-side JSON/SSE string construction for compatibility streams
  with API-layer frame builders.
- Kept native provider streaming recovery logic in `server.py` for now.

## Files Modified

- `agent_hub/api/compatibility.py`
- `agent_hub/server.py`
- `tests/test_api_compatibility_phase9.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase9.md`

## Architecture Boundary

Compatibility streaming now flows through the API layer:

```text
AgentHubHandler
  -> api.compatibility.openai_chat_sse_frames(...)
  -> api.compatibility.openai_response_sse_frames(...)
  -> api.compatibility.anthropic_sse_frames(...)
  -> socket write / flush
```

The payload helpers still produce canonical event objects, while the API layer
owns the SSE wire framing used by compatibility endpoints.

## Compatibility Contract

Existing behavior remains stable:

- OpenAI Chat streaming uses `data: ...\n\n` frames and ends with `[DONE]`
- OpenAI Responses streaming uses `data: ...\n\n` frames and ends with `[DONE]`
- Anthropic Messages streaming uses named `event:` frames with JSON `data:`
- response headers and common CORS headers are unchanged
- server disconnect handling continues to use `_safe_write()` and `_safe_flush()`

## Risks Introduced

- **Streaming frame drift risk: medium.** SSE framing is client-visible. Direct
  Phase 9 tests assert frame prefixes, JSON payloads, named event framing, and
  `[DONE]` markers.
- **Server transport risk: low.** Socket write behavior remains in `server.py`.
- **Native stream risk: low.** Native provider stream recovery was intentionally
  left in place for a future narrower extraction.

## Validation Run

- `python -m unittest tests.test_api_compatibility_phase9`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest tests.test_server tests.test_api_golden_fixtures tests.test_api_compatibility_phase7 tests.test_api_compatibility_phase8`
- `python -m unittest`
- `npm run check:version`
- `npm run package`
- `python scripts/validate_release.py --require-vsix`

## Remaining Work

- Extract native OpenAI stream chunk formatting from `server.py`.
- Move native stream recovery decisions into a streaming compatibility service.
- Split diagnostic endpoint body assembly out of the HTTP handler.

## Rollback Strategy

Move the frame loops back into `_send_openai_stream()`,
`_send_openai_response_stream()`, and `_send_anthropic_stream()`, remove
`tests/test_api_compatibility_phase9.py`, and keep using payload stream helpers
directly from the server.
