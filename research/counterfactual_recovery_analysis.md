# Counterfactual Recovery Analysis

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This analysis estimates what would have happened to existing failures under the frozen intervention policies.

## Baseline Panel

| quantity | value |
| --- | ---: |
| cloud-aligned rows | 918 |
| baseline successes | 533 |
| baseline failures | 385 |
| baseline success rate | 58.1% |
| baseline failure rate | 41.9% |
| warning-bearing failures after grounding begins | 226 |
| warning ceiling among failures | 58.7% |

## Failure-Level Counterfactual Rule

For each failed run:

| field | estimate |
| --- | --- |
| no intervention outcome | observed failure |
| intervention outcome | success if the assigned policy repairs the observed failure pathway before finalization |
| recovery probability | policy-specific recoverable share for the failure pathway |
| uncertainty | low-central-high range from prior preventable-failure estimates |

Failures without actionable evidence, without a usable grounding chain, or without an intervention-time warning receive low or zero recovery probability.

## Dominant Counterfactual Paths

| failure path | failed rows | no intervention outcome | intervention outcome if repaired | low recovered | central recovered | high recovered | central recovery probability |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| interpretation corrected | 209 | failure | success | 73.1 | 103.1 | 187.3 | 49.3% |
| action linkage corrected | 204 | failure | success | 71.4 | 96.4 | 182.8 | 47.3% |
| interpretation or action linkage corrected | 216 | failure | success | 75.6 | 106.6 | 193.6 | 49.4% |
| not in dominant pathway | 169 | failure | usually failure | 0.0 | 0.0 | 32.4 | 0.0% central |

The union row is the central recovery estimate. It avoids double-counting failures that are both misinterpreted and action-disconnected.

## Policy-Specific Counterfactuals

| policy | target failure pathway | no intervention failures | central recovered | recovery probability over all failures | uncertainty band |
| --- | --- | ---: | ---: | ---: | --- |
| Treatment A: contradiction detection | contradictory evidence/interpretation/action | 385 | 96.3 | 25.0% | 88.6-104.0 |
| Treatment B: grounding confirmation | fragile full chain | 385 | 106.6 | 27.7% | 96.3-107.8 |
| Treatment C: action consistency checks | accepted evidence disconnected from action | 385 | 90.5 | 23.5% | 84.7-96.3 |
| Treatment D: evidence verification | unsupported accepted evidence | 385 | 84.7 | 22.0% | 77.0-92.4 |
| Treatment E: combined policy | union of targeted pathways | 385 | 106.6 | 27.7% | 75.6-193.6 |

## Uncertainty Interpretation

The lower bound assumes low repair effectiveness and some intervention-induced regressions. The central estimate assumes the existing interpretation/action-linkage recovery model. The high estimate assumes strong repair effectiveness on warning-bearing failures but still remains below the theoretical warning ceiling.

| ceiling | recovered failures | recovery probability over failures | simulated success rate |
| --- | ---: | ---: | ---: |
| conservative floor | 75.6 | 19.6% | 66.3% |
| practical central | 106.6 | 27.7% | 69.7% |
| optimistic practical | 193.6 | 50.3% | 79.2% |
| theoretical warning ceiling | 226.0 | 58.7% | 82.7% |

## Determination

The counterfactual evidence supports a nonzero recovery effect, centered at 106.6 recovered failures out of 385. The true recovery ceiling is not the warning ceiling. The practical central ceiling is 27.7% of failures, with an optimistic practical bound near 50.3% and a hard warning ceiling of 58.7%.
