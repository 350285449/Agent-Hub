# GCT Model Comparison v2

## Models

| model | features | purpose |
| --- | --- | --- |
| A | K + rho + A1-A3 | capability/accessibility control |
| B | grounding only | isolates evidence-to-action conversion |
| C | commitment only | isolates branch commitment |
| D | grounding + commitment | direct GCT reduced model |
| E | full trajectory model | upper-bound trajectory comparator |

## Frozen Metrics

- Holdout performance: evaluated only on rows with `holdout=true`.
- Calibration: five-bin expected calibration error and reliability curve.
- Brier: probability forecast against binary success.
- ROC AUC: discrimination across success/failure.
- Predictive stability: bootstrap interval plus split stability across task and cloud model families.

## Acceptance Rule

GCT outperforms capability only if Model D beats Model A on holdout Brier, ROC AUC, and calibration, with bootstrap-stable direction. Model E is allowed to win; sufficiency is tested by how much of E is retained by D.

## Current Execution Status

No v2 model comparison result is claimed until the 200 frozen rows have valid cloud traces and independent outcomes.
