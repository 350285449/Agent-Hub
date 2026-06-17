# Failure Recovery Model

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. This model separates recoverable from unrecoverable failures using existing warning and repair estimates.

## Failure Classes

| class | failed rows | share of failures | recoverability | intervention |
| --- | ---: | ---: | --- | --- |
| evidence found -> misinterpreted -> wrong/no action | 209 | 54.3% | high | contradiction resolution plus evidence recheck |
| accepted evidence disconnected from action | 204 | 53.0% | high | action consistency check plus grounding confirmation |
| interpretation or action linkage union | 216 | 56.1% | high | combined policy |
| mixed/other misgrounding | 145 | 37.7% | medium | grounding confirmation if a warning is measurable |
| evidence not found/no grounding | 24 | 6.2% | low | outside intervention-only scope because retrieval would be needed |
| no usable grounding | 21 | 5.5% | very low | no grounded material exists to repair |

## Recovery Probability

| estimate | recoverable failures | share of all failures | interpretation |
| --- | ---: | ---: | --- |
| conservative floor | 75.6 | 19.6% | warnings exist but repair effect is partial |
| central recovery | 106.6 | 27.7% | best current estimate for intervention alone |
| optimistic practical | 193.6 | 50.3% | high repair effectiveness on dominant warning pathways |
| theoretical warning ceiling | 226.0 | 58.7% | all detectable failures repaired |

## Recovery Timing

| timing | recoverability | reason |
| --- | --- | --- |
| 25%-50% | highest for misinterpretation | contradiction is visible before final action |
| 50%-75% | highest for action disconnect | evidence has been accepted and action linkage can be checked |
| 75%-100% | moderate | final confirmation can repair some failures but may be late |
| after final output | low | intervention no longer changes the original outcome |

## Recovery Effectiveness By Repair

| repair | central role | effectiveness |
| --- | --- | --- |
| contradiction resolution | repairs earliest misinterpretation pathway | high when evidence is already surfaced |
| action consistency check | repairs evidence-to-action disconnect | high when accepted evidence exists |
| grounding confirmation | repairs both dominant pathways | highest single-policy coverage |
| evidence verification | repairs unsupported acceptance and retention loss | medium-high |
| evidence recheck | repairs weak interpretation cheaply | medium |

## Determination

Recoverable failures are the failures with warning-bearing grounding material already inside the run. The central recoverable count remains about 106.6 of 385 failures, or 27.7%. Unrecoverable failures are mainly those without usable evidence or without an actionable warning before finalization.
