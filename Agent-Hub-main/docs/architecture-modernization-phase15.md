# Agent-Hub Architecture Modernization Phase 1.5

Phase 1.5 introduces a shared provider capability model. The goal is to stop
recomputing provider capabilities independently in routing, provider adapters,
health scoring, and diagnostics while preserving every existing response shape.

## Summary of Changes

- Added `agent_hub.capabilities.AgentCapabilities`.
- Added `agent_capabilities(agent)` as the canonical normalization point for
  `supports_tools`, `supports_function_calling`, `supports_streaming`,
  `supports_json`, context window, and max output tokens.
- Added `agent_supports_tools(agent)` so tool-capable routing decisions use the
  same function-calling fallback everywhere.
- Wired the shared model into:
  - provider adapter base capability methods
  - provider manager model rows
  - provider health scoring
  - router capability graph
  - persisted provider health capability fields
- Added guardrail coverage for the new domain module.

## Files Modified

- `agent_hub/capabilities.py`
- `agent_hub/providers/base.py`
- `agent_hub/core/provider_manager.py`
- `agent_hub/core/health.py`
- `agent_hub/core/router.py`
- `tests/test_capabilities.py`
- `tests/test_architecture_guardrails.py`
- `docs/architecture-modernization-phase15.md`

## Compatibility Contract

No public endpoint shapes changed. The shared model intentionally preserves the
existing legacy rule:

```text
tool capable == supports_tools or supports_function_calling
```

The router capability graph still emits:

```text
tools, json, streaming, vision, context_window
```

Provider manager rows still emit:

```text
context_window, supports_streaming, supports_tools
```

## Risks Introduced

- **Capability default risk: medium-low.** `None` values must continue behaving
  like `False` for boolean capability flags. Dedicated tests now lock this down.
- **Tool-capable routing risk: medium.** Tool routing relies on the combined
  `supports_tools or supports_function_calling` rule. The new model centralizes
  that behavior and tests cover the function-calling-only case.
- **Diagnostics drift risk: low.** Capability graph keys remain unchanged; only
  their source of truth moved.
- **Health scoring drift risk: low.** Health scoring still uses the same values,
  now read through `AgentCapabilities`.

## Tests Added Or Updated

- Added capability normalization tests.
- Added base provider adapter capability tests.
- Added provider manager model row tests.
- Added router capability graph tests.
- Updated architecture guardrails to treat `agent_hub.capabilities` as a domain
  candidate and an intentional router extraction edge.

## Validation Run

- `python -m unittest tests.test_capabilities`
- `python -m unittest tests.test_architecture_guardrails`
- `python -m unittest tests.test_architecture tests.test_router tests.test_server`

## Remaining Work

- Continue removing direct capability flag checks from router recommendation and
  server model-list helpers.
- Extract concrete provider adapters from the provider facade while preserving
  facade re-exports.
- Add import-direction guardrails once adapter extraction is complete.

## Rollback Strategy

Inline the small `agent_capabilities()` calls back to the original
`AgentConfig` field checks and remove `agent_hub/capabilities.py` plus
`tests/test_capabilities.py`. No fixture or API rollback is required.
