# Hidden State Discovery

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Latent states were discovered as `H0`-`H4` from trajectory vectors. The labels are ordinal only, sorted by observed success rate after clustering; no semantic state names were assumed by the discovery step.

## Cluster Number Evidence

| k | within-cluster sum sq | WCSS improvement | success-rate spread | smallest cluster |
| --- | --- | --- | --- | --- |
| 2 | 676.641137 | n/a | 0.118666 | 307 |
| 3 | 643.269465 | 33.371671 | 0.12932 | 30 |
| 4 | 324.662121 | 318.607344 | 0.467322 | 30 |
| 5 | 241.367288 | 83.294833 | 0.494047 | 30 |
| 6 | 233.610233 | 7.757055 | 0.576271 | 11 |
| 7 | 156.123477 | 77.486756 | 0.503774 | 10 |
| 8 | 180.232412 | -24.108935 | 0.58642 | 16 |

## Hidden States

| hidden state | rows | success in state | success outside state | observed window stability |
| --- | --- | --- | --- | --- |
| H0 | 267 | 0.397004 | 0.655914 | 0.854031 |
| H1 | 277 | 0.490975 | 0.619345 | 0.854031 |
| H2 | 87 | 0.505747 | 0.588448 | 0.854031 |
| H3 | 30 | 0.6 | 0.579955 | 0.854031 |
| H4 | 257 | 0.891051 | 0.459909 | 0.854031 |

## Transition Evidence

| observed transition | edge count | success rate |
| --- | --- | --- |
| exploring->exploring | 1205 | 0.456432 |
| stuck->stuck | 634 | 0.362776 |
| converging->converging | 257 | 0.898833 |
| grounded->grounded | 243 | 0.901235 |
| grounded->converging | 231 | 0.887446 |
| stuck->exploring | 80 | 0.9125 |
| exploring->grounded | 38 | 0.789474 |
| exploring->converging | 21 | 1.0 |
| exploring->stuck | 14 | 0.642857 |
| recovered->recovered | 13 | 1.0 |
| stuck->recovered | 11 | 1.0 |
| stuck->converging | 5 | 1.0 |

## Predictive Power Over K+rho+A1-A3

| metric | value |
| --- | ---: |
| baseline holdout R2 | 0.416094 |
| hidden-state holdout R2 | 0.396391 |
| holdout gain | -0.019703 |
| baseline prospective R2 | 0.006192 |
| hidden-state prospective R2 | 0 |
| prospective gain | -0.006192 |

## Determination

Hidden execution states exist as stable empirical clusters. Their strongest evidence is diagnostic separation and transition structure; prospective power is weaker because prospective rows are reconstructed rather than freshly instrumented event streams.
