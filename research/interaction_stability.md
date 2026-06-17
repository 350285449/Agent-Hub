# Interaction Stability

Scope: cloud-only rows `918`; prior prospective reconstructed rows `67`.

## Coefficient And Effect Stability

| effect | coef mean | coef sd | coef 2.5% | coef 97.5% | positive coef share | delta R2 mean | delta R2 sd | mean rank |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| literal product | -0.261127 | 0.494233 | -1.242017 | 0.622388 | 0.288889 | 0.004477 | 0.006401 | 3.227778 |
| threshold survivor | 0.238819 | 0.092262 | 0.044693 | 0.401114 | 0.983333 | 0.039109 | 0.015025 | 1.783333 |

## Single-Feature Association

| feature | corr | AUC | single-feature R2 |
| --- | --- | --- | --- |
| distribution_shift_risk | -0.088407 | 0.502917 | 0.007816 |
| rho*distribution_shift_risk | 0.270273 | 0.606744 | 0.073047 |
| rho>distribution_shift_risk | 0.593622 | 0.782605 | 0.352388 |

## Split-Level Sign And Effect Stability

| axis | cell | rows | product delta R2 | threshold delta R2 | product delta Brier | threshold delta Brier |
| --- | --- | --- | --- | --- | --- | --- |
| repository | Agent-Hub | 566 | -0.484555 | -0.139642 | -0.129222 | -0.034066 |
| repository | ytdl_site | 176 | 0.001913 | 0.028024 | 0.000468 | 0.006854 |
| repository | face | 176 | -0.015628 | -0.069246 | -0.003761 | -0.016665 |
| category | bug_fix | 368 | -0.07977 | -0.011919 | -0.017377 | -0.002597 |
| category | code_generation | 169 | -0.035864 | 0.002284 | -0.008951 | 0.00057 |
| category | refactor | 84 | -0.011219 | -0.042678 | -0.002703 | -0.010282 |
| category | testing | 102 | -0.003136 | 0.008687 | -0.000781 | 0.002164 |
| category | analysis | 71 | 0.003269 | 0.068535 | 0.000798 | 0.016723 |
| category | architecture | 60 | 0.00764 | 0.023978 | 0.001908 | 0.005988 |
| category | documentation | 34 | -0.004641 | -1.9e-05 | -0.001144 | -4e-06 |
| category | coding | 30 | 0.068966 | 0.208817 | 0.013487 | 0.040836 |
| model | gemma4:31b-cloud | 413 | 0.0 | 0.001255 | -0.003864 | 0.00766 |
| model | nemotron-3-super:cloud | 477 | -0.031809 | -0.031809 | -0.151157 | -0.14265 |
| model | qwen3.5:cloud | 16 | 0.0 | 0.0 | 0.002348 | -0.00831 |
| dataset | unmatched_evidence_access | 40 | 0.009109 | 0.092776 | 0.002134 | 0.021744 |
| dataset | historical | 761 | -0.023132 | 0.032471 | -0.005387 | 0.007563 |
| dataset | prospective | 67 | 0.002725 | 0.052296 | 0.000496 | 0.009507 |
| dataset | deconfounded_phase1 | 50 | 0.005355 | 0.034426 | 0.00132 | 0.008483 |
| family | search-heavy | 413 | 0.0 | 0.001255 | -0.003864 | 0.00766 |
| family | reasoning | 483 | -0.036839 | -0.036839 | -0.141654 | -0.14091 |
| family | coding | 16 | 0.0 | 0.0 | 0.002348 | -0.00831 |

## Stability Verdict

Coefficient signs are not enough: the effect-size and ranking stability fail outside the selected prospective reconstruction. The threshold form is more stable than the literal product, but neither is stable enough to call a universal law.
