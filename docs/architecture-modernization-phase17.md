# Architecture Modernization Phase 17

## Scope

Phase 17 upgrades `agent-hub proof run --full` from a benchmark-only wrapper
into a release-gate proof command. The command still runs the benchmark proof
lane, then attaches a broader local runtime proof report for CI and release
validation.

## Changes

- Added `agent_hub.proof_runtime` with a reusable machine-readable
  `agent_hub.release_proof` report.
- Covered release checks for:
  - backend startup importability
  - diagnostics service payloads
  - configured provider adapter construction and health shape
  - deterministic routing simulation
  - in-process agent execution
  - workspace checkpoint rollback
  - VS Code extension connectivity modules
  - plugin lifecycle safety
  - advisory architecture guardrails
  - benchmark proof attachment
- Routed `agent-hub proof run --full` through the release proof runner.
- Kept `agent-hub proof run --coding` on the existing benchmark-only path for
  fast local proof runs.

## Compatibility

Existing benchmark report generation remains intact. The full proof lane still
runs the `proof-full` benchmark dataset and writes benchmark artifacts through
the existing benchmark proof runner. The new release proof JSON is additive and
is written to:

```text
<output-dir>/release-proof.json
```

or, when `--output-dir` is omitted:

```text
<state-dir>/proof_reports/release-proof.json
```

When `--export` is passed to `proof run --full`, the export path now receives
the release proof report, which includes compact benchmark metadata and links to
the benchmark artifacts.

## CI Gate

The release proof report includes:

```json
{
  "object": "agent_hub.release_proof",
  "ok": true,
  "ci_gate": {
    "release_blocking": false,
    "required_checks": [
      "backend_startup",
      "diagnostics",
      "provider_availability",
      "routing",
      "agent_execution",
      "patching_rollback",
      "extension_connectivity",
      "plugin_safety",
      "benchmark_validation"
    ]
  }
}
```

Architecture guardrails remain advisory in this phase so current monolith debt
does not block releases before package-by-package extraction lands.

## Verification

- `python -m unittest tests.test_runtime_proof tests.test_10_10_phase_contracts`
- `python -m unittest tests.test_runtime_proof tests.test_cli -k proof`
- `python -m unittest tests.test_proof_infrastructure`
- `python -m agent_hub.cli --config <tmp-config> proof run --full --limit 1 --output-dir <tmp-reports> --json`
