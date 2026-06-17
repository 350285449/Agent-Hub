# Commitment Measurement Implementation

Status: implemented.

Commitment metrics are calculated in `measure_commitment()` in `agent_hub/research/gct_instrumentation.py`.

## Captured Metrics

The implementation captures:

- first branch choice
- first branch choice sequence
- commitment onset sequence
- commitment strength
- branch reversals
- branch reversal event IDs
- lock-in
- invalid reason, if selection or commitment is missing

## Measurement Rules

First branch choice is the first `branch_selection` event.

Commitment onset is the first `commitment_event`.

Commitment strength is read from the event-time `commitment_strength` field on the onset event.

Branch reversals are counted from `branch_switching` events.

Lock-in is true when either:

- a commitment event explicitly sets `lock_in: true`, or
- commitment strength is at least `0.8` and no branch reversal occurs after commitment onset.

