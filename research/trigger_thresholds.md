# Trigger Threshold Analysis

Scope: cloud models only. No primitive searches. No interaction searches. No new theories. Thresholds are operational trigger rules over established Grounding Integrity warnings.

## Threshold Candidates

| warning | early trigger | late trigger | optimal trigger |
| --- | --- | --- | --- |
| contradictory grounding | any contradiction after evidence recognition | repeated contradiction after action planning | first unresolved contradiction in 25%-50% window |
| grounding collapse | first evidence-retention drop | collapse visible after action is already selected | accepted evidence no longer linked to planned action in 50%-75% window |
| grounded-action ratio decline | small decline from prior step | low ratio only at final answer | material decline plus action no longer cites/preserves accepted evidence |
| evidence-action mismatch | any weak wording mismatch | mismatch only after final output is drafted | accepted evidence supports a different action than the selected action |

## Early, Late, And Optimal Trigger Effects

| trigger family | early trigger effect | late trigger effect | optimal trigger effect |
| --- | --- | --- | --- |
| contradiction | high recall, moderate extra cost | lower recoverability because wrong action may already be selected | best early warning; trigger immediately once contradiction is decision-relevant |
| collapse | may over-trigger on temporary weak grounding | catches only mature failures | trigger once accepted evidence loses action linkage |
| grounded-action decline | may fire on harmless exploratory moves | misses action drift until final gate | trigger on decline plus action inconsistency, not decline alone |
| evidence-action mismatch | useful but can be noisy before action exists | too late after final answer is formed | trigger after action proposal and before execution/finalization |

## Recommended Thresholds

| rank | trigger mechanism | threshold | intervention |
| ---: | --- | --- | --- |
| 1 | contradictory grounding | one unresolved contradiction involving decision-relevant evidence in 25%-50% | contradiction resolution |
| 2 | evidence-action mismatch | any accepted evidence whose implication conflicts with the planned action | action consistency check |
| 3 | grounded-action ratio decline | material decline from prior grounded step plus weak action citation/linkage | action consistency check |
| 4 | grounding collapse | accepted evidence present but no longer retained in action planning | grounding confirmation |
| 5 | low evidence reuse | decision-relevant evidence appears once and is not reused before action | evidence recheck |
| 6 | unsupported accepted evidence | accepted evidence lacks source, file, test, or trace support | evidence verification |

## Timing Recommendation

| execution window | threshold stance |
| --- | --- |
| 0%-25% | do not trigger unless evidence is already decision-relevant |
| 25%-50% | aggressive contradiction threshold; moderate evidence recheck threshold |
| 50%-75% | aggressive action-consistency threshold; moderate collapse threshold |
| 75%-100% | mandatory confirmation if any earlier warning remains unresolved |

## Determination

The optimal trigger is not the lowest possible integrity score. It is the first decision-relevant contradiction after evidence appears. The second-best trigger is an evidence-action mismatch after a planned action exists. Grounded-action ratio decline is strongest as a metric, but works best as a trigger when paired with action-linkage evidence.
