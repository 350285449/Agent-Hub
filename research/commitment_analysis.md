# Commitment Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Commitment is measured as the point where prefix uncertainty falls and outcome prediction becomes materially better using strict execution prefixes.

## Prefix Commitment Curve

| prefix | features | holdout R2 | prospective R2 | uncertainty p(1-p) | collapse from 0% | entropy drop | holdout R2 delta |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% | 7 | 0.406068 | 0.0 | 0.147799 | 0.0 | 0.0 | 0.0 |
| 10% | 9 | 0.342405 | 0.0 | 0.154674 | -0.046518 | -0.006875 | -0.063663 |
| 25% | 13 | 0.423852 | 0.005219 | 0.154735 | -0.046928 | -6.1e-05 | 0.081447 |
| 50% | 17 | 0.632214 | 0.109202 | 0.088636 | 0.400294 | 0.066099 | 0.208362 |
| 75% | 21 | 0.613042 | 0.039278 | 0.095919 | 0.351017 | -0.007283 | -0.019172 |
| 90% | 24 | 0.624795 | 0.099063 | 0.096129 | 0.349597 | -0.00021 | 0.011753 |

## Commitment By Model Family

| model family | rows | success rate | branch-collapse share | mean commitment pct | success commitment pct | failure stuck share |
| --- | --- | --- | --- | --- | --- | --- |
| google | 413 | 0.956416 | 0.484262 | 50.0 | 50.0 | 0.333333 |
| nemotron-3-super | 477 | 0.289308 | 0.12369 | 50.0 | 50.0 | 0.294985 |

## Commitment By Task Family

| task family | rows | success rate | branch-collapse share | mean commitment pct | success commitment pct | failure stuck share |
| --- | --- | --- | --- | --- | --- | --- |
| agentic | 30 | 0.266667 | 0.0 | n/a | n/a | 0.954545 |
| coding | 723 | 0.603043 | 0.289073 | 50.0 | 50.0 | 0.299652 |
| reasoning | 165 | 0.539394 | 0.30303 | 50.0 | 50.0 | 0.355263 |

## Determination

Success becomes likely after branch collapse or grounded/converging execution. Failure becomes likely when the trajectory remains or ends stuck. The stable aggregate commitment point is `50%`. Commitment fraction is therefore moderately stable at the prefix level, but not stable enough across all families to be called universal.
