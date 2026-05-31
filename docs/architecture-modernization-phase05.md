# Agent-Hub Architecture Modernization Phase 0.5

Phase 0.5 captures API stability fixtures before provider extraction or router
decomposition begins. No runtime behavior was changed.

## Summary of Changes

- Added normalized golden HTTP fixtures for the primary compatibility APIs.
- Added a server-level regression test that exercises the real HTTP handler,
  router facade, payload mappers, response shapers, and compatibility streaming
  paths with a deterministic fake provider.
- Normalized dynamic request ids and timestamps in the fixtures so the tests
  protect behavior rather than incidental runtime values.

## Captured Coverage

Golden fixtures now cover:

- `/v1/chat/completions`
  - success response
  - model lookup failure response
  - compatibility streaming response
  - tool-call response
- `/v1/responses`
  - success response
  - model lookup failure response
  - compatibility streaming response
  - tool-call response
- `/v1/messages`
  - success response
  - model lookup failure response
  - Anthropic event stream response
  - tool-use response
- `/v1/models`
  - visible model aliases and agent/model rows

## Files Modified

- `tests/fixtures/phase05_api_golden.json`
- `tests/test_api_golden_fixtures.py`
- `docs/architecture-modernization-phase05.md`

## Risks Introduced

Risk is low. The new tests do not change runtime code, but they intentionally
make compatibility shape changes explicit. Future intentional compatibility
changes will need fixture updates with migration notes.

## Compatibility Considerations

The fixtures lock down:

- default hiding of routing details
- OpenAI-compatible chat response keys
- OpenAI Responses response and stream event keys
- Anthropic message and stream event keys
- model lookup failure status/body
- tool-call/tool-use transformations
- compatibility stream markers and stream-mode headers where currently present
- `/v1/models` alias visibility

## Tests Added

- `ApiGoldenFixtureTests.test_phase05_compatibility_endpoints_match_golden_fixtures`

## Remaining Work

- Add golden fixtures for native `/v1/route` and `/v1/agent` workflows when
  Phase 2 begins touching router orchestration.
- Add golden fixtures for native provider streaming before changing streaming
  service boundaries.
- Add fixture review instructions to future PR templates if the project adopts
  a formal release process.

## Rollback Strategy

Remove the Phase 0.5 test file, fixture file, and this report. No production
code needs rollback because no runtime code was changed.
