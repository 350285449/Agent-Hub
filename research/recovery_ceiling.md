# Recovery Ceiling

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This estimate answers how much performance can be recovered through intervention alone.

## Ceiling Estimates

| ceiling | prevented failures | share of failures | simulated success rate | interpretation |
| --- | ---: | ---: | ---: | --- |
| conservative floor | 75.6 | 19.6% | 66.3% | low repair effectiveness on dominant warning paths |
| practical central ceiling | 106.6 | 27.7% | 69.7% | realistic intervention-alone estimate |
| optimistic practical ceiling | 193.6 | 50.3% | 79.2% | strong repair effectiveness with low regression |
| theoretical warning ceiling | 226.0 | 58.7% | 82.7% | every detectable failure is repaired |

## Practical Ceiling

The practical recovery ceiling is the central union estimate: about 106.6 of 385 failures. That raises success from 533 of 918 rows to about 639.6 of 918 rows, or from 58.1% to 69.7%.

This is the best current estimate for intervention alone because it repairs the dominant union of interpretation and action-linkage failures without assuming perfect detection or perfect repair.

## Theoretical Ceiling

The theoretical recovery ceiling is 226 of 385 failures, or 58.7% of failures. That corresponds to the full detectable warning set after grounding begins.

This is not a deployable promise. It requires every warning-bearing failure to be detected, selected for the right repair, corrected without adding new errors, and completed before final output.

## What Intervention Alone Cannot Recover

| unrecovered class | reason intervention is limited |
| --- | --- |
| no evidence found | intervention-only control cannot repair missing grounding material |
| no usable grounding | there is no evidence chain to confirm |
| late or absent warning | control loop has no actionable signal before finalization |
| repair-induced regression | intervention may add cost or destabilize a partially correct path |

## Determination

Intervention alone can realistically recover about 27.7% of all failures, with a practical optimistic bound near 50.3% and a hard warning ceiling of 58.7%. The remaining failures require better evidence acquisition, task setup, or capabilities outside this control-only program.
