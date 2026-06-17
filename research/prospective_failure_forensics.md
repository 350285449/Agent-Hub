# Prospective Failure Forensics

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Contamination Loss

| comparison | contaminated A1-A5 R2 | clean A1-A3 R2 | R2 loss when post-run fields removed |
| --- | --- | --- | --- |
| retrospective in-sample | 0.609926 | 0.506963 | 0.102963 |
| historical/nonhistorical holdout | 0.620381 | 0.416094 | 0.204287 |
| prior prospective reconstruction | 0.113163 | 0.006192 | 0.106971 |

## Failure Causes

| cause | evidence | verdict |
| --- | --- | --- |
| leakage | A1-A5 beats A1-A3 retrospectively, and A4/A5 are generated-output traces | material cause of retrospective optimism |
| dataset size | prior prospective cloud set has only 67 reconstructed rows after filtering | material; power and coverage are weak |
| benchmark drift | prospective rows are concentrated in a narrow frozen tournament rather than the full historical distribution | likely material |
| unstable predictors | `rho` and historical priors depend on model/category cells that do not transfer cleanly | material |
| model-family effects | accepted prospective rows are dominated by a single cloud family after exclusions | material |

## Interpretation

Prospective failure is not surprising after the timing audit. Retrospective explanatory power is partly real historical structure and partly diagnostic contamination. The clean model is trying to forecast a new, narrow, imbalanced tournament using priors learned from broader historical cells.

## Primary Answer

The failure is caused by methodology more than by a disproven core theory: the retrospective design allowed historical priors and post-generation diagnostics to masquerade as predictors. The theory may still be useful diagnostically, but it has not yet earned future-outcome prediction status.
