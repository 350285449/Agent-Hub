# Interaction Deconfounding

Scope: cloud-only rows `918`; prior prospective reconstructed rows `67`.

Controls included where available: `K`, `rho`, `A1`, `A2`, `A3`, old context `A`, difficulty proxies, and retrieval/context proxies.

## Controlled Models

| model | feature count | holdout R2 | prospective R2 | delta R2 vs base | Brier gain | delta Brier vs base | calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| base K/rho/A1/old_A | 4 | 0.423589 | 0.015813 | 0.0 | 0.002875 | 0.0 | 0.070746 |
| base + shift | 5 | 0.434716 | 0.024182 | 0.008369 | 0.004396 | 0.001521 | 0.053154 |
| literal product | 6 | 0.428453 | 0.022837 | 0.007024 | 0.004151 | 0.001276 | 0.059817 |
| threshold survivor | 6 | 0.485686 | 0.064732 | 0.048919 | 0.011767 | 0.008892 | 0.06882 |
| difficulty controls | 9 | 0.388008 | 0.0 | -0.015813 | -0.009483 | -0.012358 | 0.0546 |
| retrieval controls | 9 | 0.427595 | 0.01402 | -0.001793 | 0.002549 | -0.000326 | 0.071298 |
| full deconfounded product | 15 | 0.372883 | 0.0 | -0.015813 | -0.010292 | -0.013167 | 0.080896 |
| full deconfounded threshold | 15 | 0.449569 | 0.012695 | -0.003118 | 0.002308 | -0.000567 | 0.053058 |

## Controlled Coefficients

| model | tested feature | coefficient | prospective R2 |
| --- | --- | --- | --- |
| product after controls | rho*distribution_shift_risk | -0.242231 | 0.0 |
| threshold after controls | rho>distribution_shift_risk | 0.240465 | 0.012695 |

## Deconfounding Verdict

The interaction does not clearly survive deconfounding. Most of its positive prospective gain is explained by `distribution_shift_risk` plus historical priors and accessibility/retrieval controls. After broad controls, the remaining improvement is too small and too model-dependent to be treated as independent evidence.
