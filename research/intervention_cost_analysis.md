# Intervention Cost Analysis

Scope: cloud models only. Costs are measured from frozen observed rows only.

## Observed Cost Contrast

| measure | control | treatment assignment | delta |
| --- | ---: | ---: | ---: |
| mean observed tokens per run | 5219.038627 | 4807.946903 | -411.091724 |
| mean observed latency ms per run | not estimable | not estimable | not estimable |
| delivered interventions | 0 | 0 | 0 |

## Interpretation

The true token and latency cost of the intervention policy is not estimable from this frozen randomized evidence because the treatment policy was assigned but not delivered. Historical token and latency differences reflect random assignment imbalance and underlying run variance, not intervention overhead.
