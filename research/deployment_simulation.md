# Grounding Integrity Deployment Simulation

Scope: cloud-only Agent-Hub deployment impact simulation using the established aligned cloud panel.

## Baseline

| value | count | rate |
| --- | ---: | ---: |
| aligned cloud rows | 918 | 100.0% |
| successes | 533 | 58.1% |
| failures | 385 | 41.9% |
| detectable failures after grounding begins | 226 | 58.7% of failures |
| central recoverable failures | 106.6 | 27.7% of failures |
| optimistic practical recoverable failures | 193.6 | 50.3% of failures |
| theoretical warning ceiling | 226.0 | 58.7% of failures |

## Single-Component Impact

Single-component effects overlap and should not be added linearly.

| component | estimated failure reduction | prevented failures | success increase over all rows | simulated success rate |
| --- | ---: | ---: | ---: | ---: |
| evidence recheck | 18%-22% | 69.3-84.7 | 7.5-9.2 pp | 65.6%-67.3% |
| evidence verification | 20%-24% | 77.0-92.4 | 8.4-10.1 pp | 66.4%-68.1% |
| action consistency system | 22%-25% | 84.7-96.3 | 9.2-10.5 pp | 67.3%-68.6% |
| contradiction detector and resolution | 23%-27% | 88.6-104.0 | 9.7-11.3 pp | 67.8%-69.4% |
| grounding confirmation system | 25%-28% | 96.3-107.8 | 10.5-11.7 pp | 68.6%-69.8% |

## Staged Deployment Simulation

Staged effects are incremental estimates after overlap is considered. The final central target remains bounded by the 106.6-failure union estimate unless production repair quality beats the original central assumptions.

| stage | added component | incremental prevented failures | cumulative prevented failures | failure rate | success rate |
| ---: | --- | ---: | ---: | ---: | ---: |
| 0 | no Grounding Integrity control | 0.0 | 0.0 | 41.9% | 58.1% |
| 1 | event schema and metric monitor | 8.0 | 8.0 | 41.1% | 58.9% |
| 2 | contradiction detector and resolution | 38.0 | 46.0 | 36.9% | 63.1% |
| 3 | action consistency system | 26.0 | 72.0 | 34.1% | 65.9% |
| 4 | evidence verification system | 14.0 | 86.0 | 32.6% | 67.4% |
| 5 | grounding confirmation gate | 20.6 | 106.6 | 30.3% | 69.7% |
| 6 | calibration and policy tournament | 10.0-35.0 upside | 116.6-141.6 | 26.5%-29.2% | 70.8%-73.5% |

Stage 6 is not part of the central claim. It is the measurable production upside from tuning thresholds, reducing false interventions, and improving repair prompts.

## Latency Cost

Relative latency cost uses the prior intervention cost model and assumes staged triggering rather than universal confirmation.

| component | triggered-session latency | all-session average latency | notes |
| --- | ---: | ---: | --- |
| metric monitor | +5-20 ms | +5-20 ms | mostly local event aggregation |
| contradiction detector | +150-600 ms | +40-180 ms | cheap structured comparison or compact model call |
| action consistency system | +150-700 ms | +40-220 ms | runs on material action changes |
| evidence verification system | +300-1200 ms | +70-350 ms | may require file/test/tool/source checks |
| grounding confirmation gate | +500-2000 ms | +150-600 ms | full-chain pass, mostly pre-final or severe warnings |
| full staged policy | +500-3000 ms on triggered sessions | +250-900 ms average | expected median overhead below 5%, p95 below 15% after calibration |

## Token Cost

| component | triggered-session token delta | all-session average token delta | notes |
| --- | ---: | ---: | --- |
| metric monitor | 0-100 | 0-100 | local metrics; minimal model text |
| contradiction detector | 150-600 | 40-200 | evidence and interpretation comparison |
| action consistency system | 150-700 | 40-250 | action plus accepted evidence |
| evidence verification system | 250-1000 | 60-350 | verifier context and evidence support |
| grounding confirmation gate | 400-1500 | 120-500 | compact chain confirmation |
| full staged policy | 500-2500 on triggered sessions | 250-900 average | target below 8% average token overhead |

## Success Increase

Central simulated outcome:

| policy | failures | successes | failure rate | success rate |
| --- | ---: | ---: | ---: | ---: |
| baseline | 385.0 | 533.0 | 41.9% | 58.1% |
| full staged Grounding Integrity | 278.4 | 639.6 | 30.3% | 69.7% |

Expected central improvement: 106.6 fewer failures, 106.6 additional successes, failure rate down 11.6 percentage points, success rate up 11.6 percentage points.

## Risk Sensitivity

| case | prevented failures | failure reduction | success rate |
| --- | ---: | ---: | ---: |
| conservative | 75.6 | 19.6% | 66.3% |
| central | 106.6 | 27.7% | 69.7% |
| optimistic practical | 193.6 | 50.3% | 79.2% |
| theoretical warning ceiling | 226.0 | 58.7% | 82.7% |

## Deployment Determination

The staged policy is expected to reduce failures by about 27.7% centrally after all core components ship. The best first production detector is contradiction detection. The best final gate is grounding confirmation. Token and latency costs are acceptable only if confirmation is targeted at severe or pre-final warnings rather than run on every intermediate step.
