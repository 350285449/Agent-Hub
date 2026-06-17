# Grounding Integrity Metrics

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Rules honored: cloud models only; no primitive search; no interaction search; no new theory zoo. Metrics use execution-stage variables available before the final answer, after evidence has begun to appear.

## Operational Metrics

| rank | metric | single corr | single AUC | single R2 | holdout R2 gain over K+rho+A1-A3 | prospective R2 gain | low-metric failed rows | share of failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grounded_action_ratio | 0.609686 | 0.888536 | 0.371717 | 0.139998 | 0.057341 | 352 | 0.914286 |
| 2 | evidence_reuse | 0.631308 | 0.89396 | 0.39855 | 0.124376 | 0.0515 | 357 | 0.927273 |
| 3 | evidence_action_consistency | 0.4568 | 0.812736 | 0.208667 | 0.027834 | 0.01924 | 357 | 0.927273 |
| 4 | grounding_latency_integrity | 0.143784 | 0.569194 | 0.020674 | 0.027508 | 0.035342 | 153 | 0.397403 |
| 5 | evidence_interpretation_accuracy | 0.103872 | 0.516449 | 0.010789 | 0.007119 | 0.035458 | 17 | 0.044156 |
| 6 | evidence_retention | 0.339071 | 0.696075 | 0.114969 | 0.002423 | 0.060422 | 221 | 0.574026 |

## Definitions

| metric | definition |
| --- | --- |
| evidence_interpretation_accuracy | whether retrieved/surfaced evidence becomes accepted or understood evidence |
| evidence_action_consistency | whether accepted evidence remains aligned with action linkage and grounded action |
| grounding_latency_integrity | inverse grounding latency; high means grounding occurs early |
| grounded_action_ratio | share of action trace consistent with available evidence |
| evidence_retention | whether evidence survives from recognition/acceptance into action linkage |
| evidence_reuse | whether evidence is reused in references, edits, or verification rather than mentioned once |

## Determination

Strongest individual integrity metric: `grounded_action_ratio`. The strongest pattern is not raw evidence access. It is whether evidence survives interpretation and stays connected to action.
