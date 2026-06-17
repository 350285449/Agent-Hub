# Pre-Run Prediction Framework

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Rule

A predictor is admissible only if its value can be frozen before the predicted success outcome exists. The strict initial-routing model excludes retrieval products. The clean post-retrieval model may use `A2_retrieved` and `A3_surfaced` only after the context package is frozen and before generation.

## Model Tournament

| model | features | admissibility |
| --- | --- | --- |
| K | K | clean initial |
| K+rho | K, rho | clean initial |
| K+rho+A1 | K, rho, A1_exists | clean initial |
| K+rho+A1-A3 | K, rho, A1_exists, A2_retrieved, A3_surfaced | clean post-retrieval |
| K+rho+A1-A5 | K, rho, A1_exists, A2_retrieved, A3_surfaced, A4_understood, A5_linked_to_action | diagnostic upper bound; contaminated |

## Retrospective In-Sample Recompute

| model | rows | corr | AUC | Brier | R2 |
| --- | --- | --- | --- | --- | --- |
| K | 918 | 0.692927 | 0.723925 | 0.12647 | 0.480148 |
| K+rho | 918 | 0.70976 | 0.867172 | 0.120408 | 0.503759 |
| K+rho+A1 | 918 | 0.710176 | 0.868181 | 0.120356 | 0.504349 |
| K+rho+A1-A3 | 918 | 0.712013 | 0.896411 | 0.11954 | 0.506963 |
| K+rho+A1-A5 | 918 | 0.780977 | 0.956312 | 0.089623 | 0.609926 |

## Frozen-Style Holdout Recompute

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K | 157 | 0.658603 | 0.663643 | 0.129747 | 0.22362 | 0.093872 | 0.419786 | 0.055332 |
| K+rho | 157 | 0.670606 | 0.84316 | 0.131252 | 0.22362 | 0.092367 | 0.413055 | 0.103248 |
| K+rho+A1 | 157 | 0.670606 | 0.84316 | 0.131252 | 0.22362 | 0.092367 | 0.413055 | 0.103248 |
| K+rho+A1-A3 | 157 | 0.671952 | 0.86094 | 0.130573 | 0.22362 | 0.093047 | 0.416094 | 0.102099 |
| K+rho+A1-A5 | 157 | 0.799124 | 0.938316 | 0.08489 | 0.22362 | 0.138729 | 0.620381 | 0.078606 |

## Prior Prospective Reconstruction

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K | 67 | 0.0 | 0.5 | 0.185937 | 0.181778 | -0.004159 | 0.0 | 0.064494 |
| K+rho | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001638 | 0.009013 | 0.077292 |
| K+rho+A1 | 67 | 0.248682 | 0.64951 | 0.180139 | 0.181778 | 0.001638 | 0.009013 | 0.077292 |
| K+rho+A1-A3 | 67 | 0.229719 | 0.636642 | 0.180652 | 0.181778 | 0.001126 | 0.006192 | 0.077699 |
| K+rho+A1-A5 | 67 | 0.42758 | 0.76777 | 0.161207 | 0.181778 | 0.020571 | 0.113163 | 0.11497 |

Best clean initial model: `K+rho+A1`. Best clean post-retrieval model: `K+rho+A1-A3`. `K+rho+A1-A5` is reported only to measure contamination, not as an admissible forecast model.
