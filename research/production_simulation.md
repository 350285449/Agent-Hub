# Production Simulation

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This simulation projects the central causal intervention estimate to production run volumes.

## Per-Run Rates

| measure | baseline | intervention central |
| --- | ---: | ---: |
| success rate | 58.1% | 69.7% |
| failure rate | 41.9% | 30.3% |
| failures prevented per run | 0.1161 | 0.1161 |
| success increase | +11.6 pp | +11.6 pp |

Central intervention policy: staged combined policy with overlap accounted for. It prevents 106.6 failures per 918 runs, or 116.1 failures per 1000 runs.

## Volume Simulation

| production runs | baseline failures | intervention failures | failures prevented | baseline successes | intervention successes | success increase |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 419.4 | 303.3 | 116.1 | 580.6 | 696.7 | +116.1 |
| 10,000 | 4,193.9 | 3,032.7 | 1,161.2 | 5,806.1 | 6,967.3 | +1,161.2 |
| 100,000 | 41,938.9 | 30,326.8 | 11,612.2 | 58,061.1 | 69,673.2 | +11,612.2 |

## Intervention Overhead

Using the staged combined policy evaluation constants:

| production runs | average tokens per run | total extra tokens | average latency per run | expected intervention-triggered runs |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 575 | 575,000 | 575 ms | 650 |
| 10,000 | 575 | 5,750,000 | 575 ms | 6,500 |
| 100,000 | 575 | 57,500,000 | 575 ms | 65,000 |

## Economic Projection

| production runs | failures prevented | tokens spent | tokens per failure prevented |
| ---: | ---: | ---: | ---: |
| 1,000 | 116.1 | 575,000 | 4,950 |
| 10,000 | 1,161.2 | 5,750,000 | 4,950 |
| 100,000 | 11,612.2 | 57,500,000 | 4,950 |

## Sensitivity

| production runs | conservative prevented | central prevented | optimistic practical prevented | warning-ceiling prevented |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 82.4 | 116.1 | 210.9 | 246.2 |
| 10,000 | 823.5 | 1,161.2 | 2,108.9 | 2,461.9 |
| 100,000 | 8,235.3 | 11,612.2 | 21,089.3 | 24,618.7 |

## Determination

At production scale, even the central estimate is material: about 11,612 failures prevented per 100,000 runs. The overhead is acceptable only if the combined policy remains staged and measured. Universal heavy confirmation would spend too many tokens and too much latency for the same overlap-bounded recovery ceiling.
