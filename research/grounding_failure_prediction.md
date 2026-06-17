# Grounding Failure Prediction

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Failure Detection

| model | holdout AUC | holdout Brier gain | holdout calibration error |
| --- | --- | --- | --- |
| K+rho+A1-A3 | 0.86094 | 0.093047 | 0.102099 |
| GI score only | 0.924438 | 0.051896 | 0.190075 |
| GI metrics | 0.928157 | 0.10414 | 0.164563 |
| Combined | 0.945392 | 0.13229 | 0.069208 |

## Prediction After Grounding Begins

| warning | earliest visible window | failed rows hit | share of grounding-begun failures | share of all failures |
| --- | --- | --- | --- | --- |
| delayed grounding | 25%-50% | 12 | 0.04918 | 0.031169 |
| contradictory grounding | 25%-50% | 209 | 0.856557 | 0.542857 |
| unstable grounding | 50%-75% | 161 | 0.659836 | 0.418182 |
| grounding collapse | 50%-75% | 204 | 0.836066 | 0.52987 |
| any warning after grounding begins | 25%-75% | 226 | 0.92623 | 0.587013 |

## Incremental Predictive Power

| comparison | holdout R2 | prospective R2 |
| --- | ---: | ---: |
| K+rho+A1-A3 | 0.416094 | 0.006192 |
| Grounding Integrity model | 0.465703 | 0.009762 |
| Combined model | 0.591585 | 0.069023 |
| additional over K+rho+A1-A3 | 0.175491 | 0.062831 |

## Determination

Failures can be predicted after grounding begins. The measurable warning set hits 0.92623 of grounding-begun failures and 0.587013 of all failures before final answer.
