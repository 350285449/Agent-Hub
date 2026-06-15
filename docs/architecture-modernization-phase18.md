# Architecture Modernization Phase 18

## Scope

Phase 18 strengthens the Provider Platform contract by expanding static
provider conformance from a method-surface check into named platform-readiness
dimensions.

## Changes

- Added `CONFORMANCE_DIMENSIONS` to the provider SDK.
- Extended `provider_conformance_report()` with no-network checks for:
  - `auth`
  - `streaming`
  - `tools`
  - `retries`
  - `errors`
  - `timeouts`
  - `costs`
- Exported the dimension list from both `agent_hub.providers` and
  `agent_hub.providers.sdk`.
- Updated provider SDK tests and docs so provider authors can treat these
  dimensions as the stable adapter maturity checklist.

## Compatibility

Existing provider adapters keep the same runtime behavior. The report shape is
additive: existing callers still receive `object`, `ok`, `rating`, `checks`, and
`contract`; the `contract.dimensions` list and new check rows provide more
detail without requiring network calls.

## Verification

- `python -m unittest tests.test_provider_sdk tests.test_architecture_guardrails`
