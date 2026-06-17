# Prospective Validation

This file freezes the next validation protocol rather than claiming a new prospective result. Metrics, thresholds, models, and definitions must be frozen before observing new outcomes.

## Frozen Definitions

- Variables: current K, rho, clean Accessibility 2.0 pre-run components A1-A3, and current Evidence Access A for continuity.
- Excluded from initial prediction: E9, output references, edited files, verifier commands, post-run diagnostics.
- Primary model: logistic/linear calibration on frozen K+rho+A, no threshold tuning after outcomes.
- Success probability: predicted before outcome with 95% bootstrap confidence interval.
- New benchmark set: must not overlap current `row_id`, task prompt, or benchmark label cells.

## Retrospective Holdout Sanity Check

| split | rows | corr | AUC | Brier | R2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| frozen-style holdout | 229 | 0.725482 | 0.906907 | 0.11766 | 0.526324 |

This is not accepted as prospective evidence. It is included only to verify that the frozen machinery produces sensible outputs.

## Acceptance Rules

- Calibration error <= 0.10.
- Brier beats base-rate predictor by >= 0.03.
- Reliability curve monotonic across at least four populated bins.
- Measurement ceiling remains >= 0.70 after excluding post-run fields.
- A fourth primitive is considered only if residual structure remains stable after upgraded K/rho/A and frozen validation.

Current ceiling prior for planning: `0.770533`.
