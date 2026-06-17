# GCT Model Comparison

Models were trained on the non-holdout slice of the fresh prospective panel and scored on the frozen holdout slice.

| model | holdout rows | R2 | Brier | ROC AUC | calibration error | Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| A. K + rho + A1-A3 | 5 | 0.815753 | 0.029479 | 1.0 | 0.10433 | 0.130521 |
| B. Grounding only | 5 | 0.270746 | 0.116681 | 1.0 | 0.112966 | 0.043319 |
| C. Commitment only | 5 | 0.0 | 0.342653 | 0.125 | 0.485827 | -0.182653 |
| D. Grounding + Commitment | 5 | 0.314541 | 0.109673 | 1.0 | 0.279817 | 0.050327 |
| E. Full trajectory model | 5 | 0.0 | 0.424933 | 0.125 | 0.422684 | -0.264933 |

## Determination

The direct GCT model is Model D. It must beat the capability model A and remain near the full trajectory model E to survive this phase.
