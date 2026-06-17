# Hidden State Theory

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Falsification stance: assume labels such as grounded/exploring/converging/stuck/confused/recovered are decorative aliases for K, rho, and A.

## State Outcome Rates

| state | rows in state | success when present | success when absent |
| --- | --- | --- | --- |
| grounded | 249 | 0.88755 | 0.466368 |
| exploring | 234 | 0.444444 | 0.627193 |
| converging | 259 | 0.899614 | 0.455235 |
| stuck | 184 | 0.271739 | 0.658038 |
| confused | 171 | 0.438596 | 0.613119 |
| recovered | 13 | 1.0 | 0.574586 |

## Frequent State Sequences

| 10>25>50>75 sequence | rows | success rate |
| --- | --- | --- |
| exploring>stuck>converging>converging | 13 | 1.0 |
| stuck>stuck>recovered>recovered | 11 | 1.0 |
| exploring>exploring>converging>converging | 8 | 1.0 |
| grounded>grounded>converging>converging | 193 | 0.906736 |
| stuck>stuck>exploring>converging | 10 | 0.9 |
| grounded>grounded>converging>stuck | 16 | 0.875 |
| stuck>grounded>converging>converging | 38 | 0.789474 |
| exploring>stuck>converging>stuck | 16 | 0.625 |
| stuck>exploring>confused>confused | 87 | 0.505747 |
| stuck>stuck>exploring>stuck | 254 | 0.448819 |
| exploring>exploring>confused>confused | 84 | 0.369048 |
| exploring>stuck>exploring>stuck | 160 | 0.36875 |
| exploring>exploring>exploring>stuck | 19 | 0.368421 |

## Incremental Test Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| baseline holdout R2 | 0.416094 |
| hidden-state holdout R2 | 0.51276 |
| holdout gain | 0.096666 |
| baseline prospective R2 | 0.006192 |
| hidden-state prospective R2 | 0 |
| prospective gain | -0.006192 |

## Determination

Hidden states exist as useful diagnostic summaries of trajectories. They explain more holdout variance than K, rho, and A1-A3 alone if the gain is positive; they are not yet validated as clean prospective states because the prospective panel contains reconstructed, not freshly frozen, state features.

Verdict: survives diagnostically, weakened predictively.
