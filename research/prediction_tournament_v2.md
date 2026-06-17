# Prediction Tournament v2

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Retrospective

| model | features | rows | corr | AUC | Brier | R2 |
| --- | --- | --- | --- | --- | --- | --- |
| Existing K+rho+A | K, rho, A1_exists, old_A | 918 | 0.711601 | 0.893965 | 0.119748 | 0.506376 |
| Best primitive model | K, rho, A1_exists, old_A, search_complexity | 918 | 0.713459 | 0.89529 | 0.119258 | 0.509023 |
| Best interaction model | K, rho, A1_exists, old_A, rho, distribution_shift_risk, rho>distribution_shift_risk | 918 | 0.722802 | 0.903243 | 0.116243 | 0.522442 |
| Best difficulty model | K, rho, A1_exists, old_A, difficulty_novelty_planning | 918 | 0.712855 | 0.894428 | 0.119369 | 0.508162 |
| Best causal model | K, rho, A1_exists, old_A, distribution_shift_risk, rho>distribution_shift_risk | 918 | 0.722802 | 0.903243 | 0.116243 | 0.522442 |
| Best combined model | A1_exists, K, difficulty_novelty_planning, distribution_shift_risk, old_A, rho, rho>distribution_shift_risk, search_complexity | 918 | 0.723467 | 0.902985 | 0.115956 | 0.523405 |

## Holdout

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Existing K+rho+A | 157 | 0.671355 | 0.86103 | 0.128897 | 0.22362 | 0.094723 | 0.423589 | 0.077267 |
| Best primitive model | 157 | 0.672206 | 0.867652 | 0.127213 | 0.22362 | 0.096406 | 0.431117 | 0.077818 |
| Best interaction model | 157 | 0.698854 | 0.885704 | 0.115011 | 0.22362 | 0.108609 | 0.485686 | 0.046005 |
| Best difficulty model | 157 | 0.668977 | 0.857402 | 0.127353 | 0.22362 | 0.096267 | 0.430493 | 0.06153 |
| Best causal model | 157 | 0.698854 | 0.885704 | 0.115011 | 0.22362 | 0.108609 | 0.485686 | 0.046005 |
| Best combined model | 157 | 0.700788 | 0.885795 | 0.115331 | 0.22362 | 0.108288 | 0.484252 | 0.063233 |

## Prospective Reconstruction

| model | rows | corr | AUC | Brier | base Brier | Brier gain | R2 | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Existing K+rho+A | 67 | 0.254409 | 0.670956 | 0.178903 | 0.181778 | 0.002875 | 0.015813 | 0.070746 |
| Best primitive model | 67 | 0.239138 | 0.662377 | 0.177151 | 0.181778 | 0.004627 | 0.025455 | 0.050911 |
| Best interaction model | 67 | 0.257697 | 0.710172 | 0.170011 | 0.181778 | 0.011767 | 0.064732 | 0.06882 |
| Best difficulty model | 67 | 0.225177 | 0.678309 | 0.177196 | 0.181778 | 0.004582 | 0.025207 | 0.04978 |
| Best causal model | 67 | 0.257697 | 0.710172 | 0.170011 | 0.181778 | 0.011767 | 0.064732 | 0.06882 |
| Best combined model | 67 | 0.258127 | 0.668505 | 0.169874 | 0.181778 | 0.011904 | 0.065487 | 0.022495 |

## Result

Best prospective reconstruction: `Best combined model` with R2 `0.065487` and Brier gain `0.011904`. Ceiling escaped: `True`. Retrospective and holdout improvements remain much larger than clean prospective improvements, which is the signature of diagnostic rather than predictive science.
