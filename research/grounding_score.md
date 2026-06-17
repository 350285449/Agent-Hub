# Grounding Score

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Score formula uses only the four allowed quantities:

`mean(1 - decisive_evidence_timing, 1 - grounding_latency, grounded_action_ratio, 1 - evidence_to_action_latency)`.

## Score Performance

| metric | value |
| --- | ---: |
| single-score retrospective corr | 0.369126 |
| single-score retrospective AUC | 0.763644 |
| single-score retrospective R2 | 0.136254 |
| single-score holdout R2 | 0.075283 |
| single-score prospective R2 | 0 |
| full grounding-feature holdout R2 | 0.359202 |
| K+rho+A1-A3+grounding holdout R2 | 0.571255 |
| full dynamic-model holdout R2 | 0.611615 |
| score share of grounding holdout R2 | 0.209584 |
| score share of dynamic holdout R2 | 0.123089 |
| score share of dynamic prospective R2 | 0 |
| grounding share of incremental dynamic holdout signal | 0.793577 |
| grounding share of incremental dynamic prospective signal | 0.617598 |

## Determination

The score is a compact execution diagnostic, but it should not replace the larger execution model yet. It captures much of the grounding-specific signal when latency and action conversion are the target, but the richer dynamic model still carries additional information from verification, recovery, and branch-collapse events.
