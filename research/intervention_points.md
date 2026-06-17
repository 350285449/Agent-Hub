# Intervention Points

Scope: cloud models only. No primitive search, no interaction search, no new theory. This report reuses the measured grounding-integrity corpus: 918 cloud-only aligned rows, 385 failures, and the existing execution-stage grounding variables.

## Measured Failure Onsets

| event | earliest visible window | failed rows hit | share of all failures | operational meaning | intervention status |
| --- | ---: | ---: | ---: | --- | --- |
| first contradictory grounding | 25%-50% | 209 | 54.3% | surfaced evidence conflicts with the interpretation trace | earliest high-value intervention point |
| first integrity degradation | 25%-50% | 209 | 54.3% | recognized evidence fails to become coherent interpretation, usually visible as contradiction before collapse | earliest practical repair point |
| first grounding collapse | 50%-75% | 204 | 53.0% | accepted evidence no longer remains connected to action | second intervention point, still recoverable |
| first action disconnect | 50%-75% | 204 | 53.0% | action selection stops preserving the accepted evidence link | last strong intervention point before final answer |

## Timing Determination

The first intervention opportunity is the 25%-50% execution window, when contradictory grounding first appears. This is earlier than grounding collapse and action disconnect, which become visible in the 50%-75% window.

The strongest early signal is not evidence absence. The dominant failure chain is evidence found, misinterpreted, then converted into wrong or missing action. That makes the first practical intervention an interpretation repair, not a retrieval expansion.

## Intervention Windows

| window | observable state | best intervention | expected recoverable share |
| --- | --- | --- | ---: |
| 0%-25% | evidence has not yet stabilized | no strong intervention supported by this corpus | low |
| 25%-50% | contradiction or weak interpretation appears | contradiction detection and evidence recheck | high |
| 50%-75% | accepted evidence loses action linkage | action consistency check and grounding confirmation | high but later |
| 75%-100% | output is mostly committed | final verification only | low to moderate |

## Early Intervention Estimate

Warnings after grounding begins hit 226 failures, or 58.7% of all failures. The realistic central preventable subset from correcting interpretation or action linkage is 106.6 failures, or 27.7% of all failures.

This means intervention can begin early for more than half of failures, but the realistically recoverable central estimate is about one quarter to one third of failures because not every warning can be converted into a successful repair.

## Direct Answer

The first intervention opportunity is contradictory grounding in the 25%-50% execution window. Intervention after grounding collapse remains useful, but it is later and should be treated as repair rather than prevention.
