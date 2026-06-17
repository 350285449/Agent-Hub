# Intervention Simulation

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This simulation uses the established cloud-only failure counts and counterfactual repair estimates.

Baseline: 918 aligned cloud rows, 385 failures, 533 successes. Detectable failures after grounding begins: 226, or 58.7% of failures. Central recoverable failures: 106.6, or 27.7% of failures.

## Simulated Interventions

| intervention | target warning | estimated failure reduction | prevented failures | success increase over all rows | cost | cost reading |
| --- | --- | ---: | ---: | ---: | --- | --- |
| grounding confirmation | fragile or collapsing chain | 25%-28% | 96.3-107.8 | 10.5-11.7 pp | high | full evidence-interpretation-action pass |
| contradiction resolution | contradictory grounding | 23%-27% | 88.6-104.0 | 9.7-11.3 pp | moderate | compare surfaced evidence to interpretation before action |
| action consistency check | low grounded-action ratio or evidence-action mismatch | 22%-25% | 84.7-96.3 | 9.2-10.5 pp | moderate | require action to preserve accepted evidence |
| evidence verification | accepted evidence without source/test/file support | 20%-24% | 77.0-92.4 | 8.4-10.1 pp | moderate-high | verify evidence against concrete context |
| evidence recheck | low evidence reuse or weak interpretation | 18%-22% | 69.3-84.7 | 7.5-9.2 pp | low-moderate | reread already surfaced evidence |

## Central Simulation

| policy | baseline failures | prevented failures | simulated failures | simulated successes | failure rate | success rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| no intervention | 385.0 | 0.0 | 385.0 | 533.0 | 41.9% | 58.1% |
| evidence recheck | 385.0 | 77.0 | 308.0 | 610.0 | 33.6% | 66.4% |
| evidence verification | 385.0 | 84.7 | 300.3 | 617.7 | 32.7% | 67.3% |
| action consistency check | 385.0 | 90.5 | 294.5 | 623.5 | 32.1% | 67.9% |
| contradiction resolution | 385.0 | 96.3 | 288.7 | 629.3 | 31.4% | 68.6% |
| grounding confirmation | 385.0 | 106.6 | 278.4 | 639.6 | 30.3% | 69.7% |

## Combined Intervention Simulation

The interventions overlap because the dominant failure pathways overlap. The combined policy cannot add the single-policy estimates linearly. Its realistic central effect is bounded by the established union estimate: 106.6 prevented failures. Its practical high estimate is 193.6 prevented failures if repair effectiveness is unusually strong and warnings are handled without regressions.

| combined policy case | prevented failures | failure rate | success rate | interpretation |
| --- | ---: | ---: | ---: | --- |
| conservative | 75.6 | 33.7% | 66.3% | low repair effectiveness on the dominant union |
| central | 106.6 | 30.3% | 69.7% | current best estimate |
| optimistic practical | 193.6 | 20.8% | 79.2% | high repair success on detected interpretation/action-link failures |
| theoretical warning ceiling | 226.0 | 17.3% | 82.7% | all detectable failures repaired; not operationally realistic |

## Cost Model

| intervention | relative cost units | best use |
| --- | ---: | --- |
| evidence recheck | 1 | cheap first response to weak evidence reuse |
| contradiction resolution | 2 | first serious trigger after evidence appears |
| action consistency check | 2 | every material action change after evidence acceptance |
| evidence verification | 3 | when accepted evidence lacks a concrete verifier |
| grounding confirmation | 4 | severe warning or pre-final gate |

## Determination

Grounding confirmation produces the largest single-policy outcome change. Contradiction resolution has the best early timing. Action consistency has the best direct control over the strongest metric, grounded-action ratio. The combined policy wins only when it is staged to avoid paying the full confirmation cost on every minor warning.
