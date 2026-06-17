# Grounding Integrity Assessment

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Answers

1. Can misgrounding be detected early? Yes. Warning signals appear after evidence recognition and before final answer, especially contradictory grounding and grounding collapse.
2. What is the earliest warning sign? `contradictory grounding` in this measured panel.
3. Which integrity metric is strongest? `grounded_action_ratio` by incremental holdout gain/AUC ordering.
4. Can grounding integrity predict failure? Yes diagnostically: the combined model improves holdout R2 over `K+rho+A1-A3` by 0.175491.
5. How many failures become predictable after grounding begins? 226 rows, or 0.587013 of all failures.
6. How many failures become preventable? Central estimate is 106.5 rows from weak-integrity candidate failures, or 0.276582 of all failures; the operationally predictable subset is 106.5 rows, or 0.276582.

## Ranked Grounding Integrity Metrics

| rank | metric | single corr | single AUC | single R2 | holdout R2 gain over K+rho+A1-A3 | prospective R2 gain | low-metric failed rows | share of failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | grounded_action_ratio | 0.609686 | 0.888536 | 0.371717 | 0.139998 | 0.057341 | 352 | 0.914286 |
| 2 | evidence_reuse | 0.631308 | 0.89396 | 0.39855 | 0.124376 | 0.0515 | 357 | 0.927273 |
| 3 | evidence_action_consistency | 0.4568 | 0.812736 | 0.208667 | 0.027834 | 0.01924 | 357 | 0.927273 |
| 4 | grounding_latency_integrity | 0.143784 | 0.569194 | 0.020674 | 0.027508 | 0.035342 | 153 | 0.397403 |
| 5 | evidence_interpretation_accuracy | 0.103872 | 0.516449 | 0.010789 | 0.007119 | 0.035458 | 17 | 0.044156 |
| 6 | evidence_retention | 0.339071 | 0.696075 | 0.114969 | 0.002423 | 0.060422 | 221 | 0.574026 |

## Model Comparison

| model | feature count | retro R2 | holdout R2 | holdout AUC | holdout Brier gain | holdout calibration error | prospective R2 | prospective AUC | prospective Brier gain | prospective calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K+rho+A1-A3 | 5 | 0.506963 | 0.416094 | 0.86094 | 0.093047 | 0.102099 | 0.006192 | 0.636642 | 0.001126 | 0.077699 |
| Grounding model | 4 | 0.37472 | 0.359202 | 0.910649 | 0.080325 | 0.208697 | 0.0 | 0.565564 | -0.028727 | 0.184897 |
| Grounding Integrity model | 6 | 0.425795 | 0.465703 | 0.928157 | 0.10414 | 0.164563 | 0.009762 | 0.679534 | 0.001775 | 0.102562 |
| Combined model | 14 | 0.59229 | 0.591585 | 0.945392 | 0.13229 | 0.069208 | 0.069023 | 0.685662 | 0.012547 | 0.069374 |

## Final Requirement

Additional predictive power over `K+rho+A1-A3`: holdout R2 +0.175491 for the combined grounding-integrity model. In the reconstructed prospective panel the additional R2 is 0.062831, so the robust claim is diagnostic/online failure detection rather than clean future prediction before execution.
