# Instrumentation Architecture

Status: implemented.

Primary code:

- `agent_hub/research/gct_instrumentation.py`
- `scripts/frozen_panel_executor.py`
- `tests/test_gct_instrumentation.py`

The instrumentation layer records one append-only JSON object per event line. Each row execution gets its own run directory under `.agent-hub/research/gct_frozen_panel_runs/<row_id>/` with:

- `events.jsonl`
- `raw_trace.json`
- `gar.json`
- `commitment_metrics.json`
- `outcome_metrics.json`

## Event Coverage

Implemented event types:

- `evidence_discovery`
- `evidence_recognition`
- `evidence_interpretation`
- `justification_event`
- `branch_creation`
- `branch_selection`
- `branch_switching`
- `commitment_event`
- `uncertainty_estimate`
- `intervention_event`
- `outcome_event`
- `run_started`
- `run_completed`

Each event stores:

- `ledger_version`
- `run_id`
- `trial_id`
- `row_id`
- `seq`
- `event_id`
- `timestamp`
- `monotonic_ms`
- `event_type`
- optional branch fields
- optional evidence unit
- `evidence_refs`
- event-time `local_grounding`
- optional uncertainty
- optional commitment strength
- optional lock-in flag
- payload

## Reproducibility

Run IDs are deterministic from `trial_id`, `row_id`, and seed. Event IDs are deterministic from run, row, sequence, event type, branch, and evidence unit. The executor sorts frozen rows by `frozen_order`.

The executor refuses non-200 panels unless `--allow-incomplete` is explicitly provided.

