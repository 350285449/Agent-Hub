# Agent-Hub Architecture Modernization Phase 1

Phase 1 extracts provider support responsibilities out of the provider facade
without changing routing behavior or public imports. The provider adapter classes
remain reachable from `agent_hub.providers`; extracted modules now own registry,
transport, quota parsing, and provider error classification.

## Summary of Changes

- Added a provider registry module with normalized provider key selection.
- Moved provider HTTP and streaming transport helpers into a transport module.
- Moved provider error classification, structured error conversion, and error
  message extraction into an errors module.
- Moved rate-limit/quota header parsing and cooldown calculation into a quota
  module.
- Kept compatibility shims in `agent_hub.providers` for existing imports and
  existing test patch points such as `agent_hub.providers._post_json`.
- Updated architecture guardrails so provider-local extraction modules do not
  count as increased cross-layer fan-out from the compatibility facade.

## Files Modified

- `agent_hub/providers/__init__.py`
- `agent_hub/providers/errors.py`
- `agent_hub/providers/quota.py`
- `agent_hub/providers/registry.py`
- `agent_hub/providers/transport.py`
- `tests/test_providers.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase1.md`

## Compatibility Contract

Existing imports continue to resolve from `agent_hub.providers`:

- `ProviderError`
- `_classify_provider_error`
- `_extract_error_message`
- `_metadata_cooldown_seconds`
- `_post_json`
- `_post_stream_json`
- `_provider_error_category`
- `_provider_error_from_http`
- `_provider_error_from_payload`
- `_provider_request_id`
- `_provider_user_message`
- `_quota_metadata_from_headers`
- `_looks_like_timeout`

Existing provider adapter imports remain unchanged:

- `OpenAIChatProvider`
- `LocalResearchProvider`
- `AnthropicMessagesProvider`
- `GeminiProvider`
- `EchoProvider`
- `create_provider`

## Current Provider Boundary

```text
agent_hub.providers
  compatibility facade
  adapter classes retained for public API stability
  create_provider delegates to ProviderRegistry

agent_hub.providers.registry
  provider key normalization
  provider factory lookup

agent_hub.providers.transport
  HTTP POST transport
  streaming SSE-style JSON transport
  provider request id extraction
  network timeout detection

agent_hub.providers.errors
  ProviderError
  error taxonomy
  structured error mapping
  provider payload/HTTP error conversion

agent_hub.providers.quota
  rate-limit header normalization
  quota metadata extraction
  cooldown calculation
```

## Risks Introduced

- **Registry dispatch risk: low.** `create_provider` now delegates through
  `ProviderRegistry`, but the normalized provider keys mirror the previous
  conditional order and focused alias tests cover the mapping.
- **Import compatibility risk: low.** The provider facade re-exports the moved
  names and tests assert object identity for representative shims.
- **Patch-point risk: low.** `_post_json_with_output_retry` still calls the
  facade-level `_post_json`, preserving existing test and downstream monkeypatch
  behavior.
- **Transport behavior risk: medium-low.** Transport code was moved
  mechanically. Focused streaming and resilience tests cover malformed chunks,
  provider errors, quota metadata, and debug logging paths.
- **Architecture guardrail risk: low.** The fan-out guardrail now exempts only
  provider-local extraction edges, preserving the Phase 0 baseline for
  cross-layer dependencies.

## Tests Added Or Updated

- Added provider facade shim identity checks.
- Added provider registry key normalization checks.
- Added provider registry factory dispatch checks.
- Updated architecture fan-out guardrail to distinguish provider-local
  extraction edges from cross-layer coupling growth.
- Regenerated the local ignored backend snapshot so packaging validation reflects
  the extracted provider files.

## Validation Run

- `python -m unittest tests.test_providers`
- `python -m unittest tests.test_resilience tests.test_phase6_10`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest tests.test_phase8_packaging`
- `python -m unittest`

## Remaining Work

- Extract provider adapter classes from the compatibility facade into adapter
  modules while keeping facade re-exports.
- Move OpenAI/Anthropic/Gemini payload mapping helpers behind adapter-specific
  modules or a provider-normalization boundary.
- Decide whether local research remains a provider adapter or becomes a tool
  execution workflow backed by provider results.
- Add import-direction guardrails for provider modules once adapter extraction
  is complete.

## Rollback Strategy

Restore the provider helper implementations into `agent_hub/providers/__init__.py`
and remove the four extracted modules plus the new registry tests. Because
public imports were preserved, rollback does not require API fixture changes.
