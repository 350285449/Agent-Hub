# Interaction Replication

Scope: cloud-only rows `918`; prior prospective reconstructed rows `67`.

## Primary Recompute

| model | holdout rows | holdout R2 | holdout delta R2 | prospective rows | prospective R2 | prospective delta R2 | prospective delta Brier gain |
| --- | --- | --- | --- | --- | --- | --- | --- |
| existing | 157 | 0.423589 | 0.0 | 67 | 0.015813 | 0.0 | 0.0 |
| literal product | 157 | 0.428453 | 0.004864 | 67 | 0.022837 | 0.007024 | 0.001276 |
| threshold survivor | 157 | 0.485686 | 0.062097 | 67 | 0.064732 | 0.048919 | 0.008892 |
| prior combined | 157 | 0.482362 | 0.058773 | 67 | 0.066981 | 0.051168 | 0.009301 |

## Split Replication

| split | train | test | product delta R2 | threshold delta R2 | product delta Brier | threshold delta Brier |
| --- | --- | --- | --- | --- | --- | --- |
| dataset split | 761 | 157 | 0.004864 | 0.062097 | 0.001087 | 0.013886 |
| prospective reconstruction | 761 | 67 | 0.007024 | 0.048919 | 0.001276 | 0.008892 |
| repository hash split | 734 | 184 | -0.000229 | -0.010259 | -5.6e-05 | -0.002514 |
| category hash split | 734 | 184 | -0.007059 | -0.007887 | -0.001724 | -0.001926 |
| model hash split | 734 | 184 | -0.004874 | 0.006048 | -0.001195 | 0.001481 |
| random 80/20 seed 0 | 734 | 184 | 0.001901 | 0.033458 | 0.000461 | 0.008112 |
| random 80/20 seed 1 | 734 | 184 | -0.008285 | -0.008625 | -0.002042 | -0.002126 |
| random 80/20 seed 2 | 734 | 184 | -0.009499 | -0.019077 | -0.002341 | -0.004701 |
| random 80/20 seed 3 | 734 | 184 | -0.00201 | -0.033574 | -0.000497 | -0.008313 |
| random 80/20 seed 4 | 734 | 184 | -0.002949 | 0.012973 | -0.000695 | 0.003058 |

## Bootstrap Replication

| quantity | mean | 2.5% | 97.5% | positive share |
| --- | --- | --- | --- | --- |
| literal product delta R2 | 0.004902 | -0.008074 | 0.018873 | 0.75625 |
| threshold delta R2 | 0.04117 | 0.009617 | 0.059105 | 0.9875 |
| literal product delta Brier gain | 0.001111 | -0.002794 | 0.004276 | 0.83125 |
| threshold delta Brier gain | 0.008066 | 0.00209 | 0.014208 | 0.9875 |

## Leave-One-Out Replication

| held-out axis | held-out value | test rows | product delta R2 | threshold delta R2 | product delta Brier | threshold delta Brier |
| --- | --- | --- | --- | --- | --- | --- |
| category | analysis | 71 | 0.003269 | 0.068535 | 0.000798 | 0.016723 |
| category | architecture | 60 | 0.00764 | 0.023978 | 0.001908 | 0.005988 |
| category | bug_fix | 368 | -0.07977 | -0.011919 | -0.017377 | -0.002597 |
| category | code_generation | 169 | -0.035864 | 0.002284 | -0.008951 | 0.00057 |
| category | coding | 30 | 0.068966 | 0.208817 | 0.013487 | 0.040836 |
| category | documentation | 34 | -0.004641 | -1.9e-05 | -0.001144 | -4e-06 |
| category | refactor | 84 | -0.011219 | -0.042678 | -0.002703 | -0.010282 |
| category | testing | 102 | -0.003136 | 0.008687 | -0.000781 | 0.002164 |
| model family | coding | 16 | 0.0 | 0.0 | 0.002348 | -0.00831 |
| model family | reasoning | 483 | -0.036839 | -0.036839 | -0.141654 | -0.14091 |
| model family | search-heavy | 413 | 0.0 | 0.001255 | -0.003864 | 0.00766 |

## Replication Verdict

The literal product does not replicate the prior positive result; the threshold variant replicates weakly in the selected prospective reconstruction but fails multiple held-out cell tests.
