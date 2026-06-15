# Architecture Modernization Phase 16

## Scope

Phase 16 turns the architecture guardrail report into a broader platform
contract while preserving existing behavior. The report remains advisory by
default, so current large modules continue to run while future release gates can
opt into enforcement.

## Changes

- Extended `agent_hub.architecture.architecture_guardrail_report` with:
  - max function size findings
  - internal import cycle findings
  - API -> application -> services -> core -> adapters layer violations
  - public API stability findings
- Kept the existing file-size report fields and `FileSizeFinding` export
  compatible for older callers.
- Exported the new finding dataclasses from `agent_hub.architecture`.
- Refreshed the current fan-out baseline for `agent_hub.server` and
  `agent_hub.cli` so the guardrail suite represents the current checkout before
  the next extraction pass.

## Compatibility

No endpoints, provider contracts, config fields, CLI commands, VS Code behavior,
or runtime workflows changed. Existing callers can continue using:

```python
from agent_hub.architecture import architecture_guardrail_report
```

The added report fields are additive and machine-readable through
`ArchitectureGuardrailReport.to_dict()`.

## Migration Notes

Release tooling can now call:

```python
architecture_guardrail_report(root, enforce=True)
```

to fail on file-size, function-size, cycle, layer, or API stability findings.
During the monolith extraction period, keep production gates advisory unless a
specific subpackage has first been brought under the limits.

## Verification

- `python -m unittest tests.test_10_10_phase_contracts tests.test_architecture_guardrails`
- `python -m unittest tests.test_architecture`
