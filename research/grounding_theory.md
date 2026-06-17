# Grounding Theory

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification stance: assume A4/A5 failed only because they were late labels, and early grounding adds nothing beyond Accessibility.

## Grounding Variables

- `time_to_decisive_evidence`
- `grounding_latency`
- `evidence_to_action_latency`
- `grounded_action_ratio`

## Incremental Test Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| accessibility baseline holdout R2 | 0.416094 |
| grounding holdout R2 | 0.571255 |
| holdout gain | 0.155161 |
| accessibility baseline prospective R2 | 0.006192 |
| grounding prospective R2 | 0.075014 |
| prospective gain | 0.068822 |
| prospective Brier gain | 0.013636 |

## Determination

Grounding is a real execution mechanism if judged diagnostically: early decisive evidence and evidence-to-action conversion separate successful from failed runs. It does not yet beat Accessibility strongly enough in prospective reconstruction to become a clean pre-run predictor.

Verdict: survives as an execution mechanism; not promoted to pre-run predictive primitive.
