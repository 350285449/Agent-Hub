# Grounding Integrity Score

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Formula:

`0.25*interpretation_accuracy + 0.24*action_consistency + 0.16*latency_integrity + 0.16*grounded_action_ratio + 0.11*evidence_retention + 0.08*evidence_reuse`

All inputs are execution-stage variables available before final answer once grounding begins.

## Score Bands

| band | rows | share | success rate | mean score |
| --- | --- | --- | --- | --- |
| collapsed | 23 | 0.025054 | 0.26087 | 0.060281 |
| fragile | 605 | 0.659041 | 0.438017 | 0.421532 |
| coherent | 15 | 0.01634 | 1.0 | 0.571862 |
| strong | 275 | 0.299564 | 0.898182 | 0.862919 |

## Model Performance

| model | feature count | retro R2 | holdout R2 | holdout AUC | holdout Brier gain | holdout calibration error | prospective R2 | prospective AUC | prospective Brier gain | prospective calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| K+rho+A1-A3 | 5 | 0.506963 | 0.416094 | 0.86094 | 0.093047 | 0.102099 | 0.006192 | 0.636642 | 0.001126 | 0.077699 |
| Grounding model | 4 | 0.37472 | 0.359202 | 0.910649 | 0.080325 | 0.208697 | 0.0 | 0.565564 | -0.028727 | 0.184897 |
| Grounding Integrity model | 6 | 0.425795 | 0.465703 | 0.928157 | 0.10414 | 0.164563 | 0.009762 | 0.679534 | 0.001775 | 0.102562 |
| Combined model | 14 | 0.59229 | 0.591585 | 0.945392 | 0.13229 | 0.069208 | 0.069023 | 0.685662 | 0.012547 | 0.069374 |

## Determination

The Grounding Integrity Score is a compact online diagnostic. It is less complete than the full metric vector, but its bands are interpretable: collapsed and fragile integrity are failure-prone, while strong integrity is the observed counterfactual target for prevention.
