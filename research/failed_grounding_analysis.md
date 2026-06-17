# Failed Grounding Analysis

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Ranked Grounding Failure Modes

| ranked failure mode | failed rows | share of failures | all rows with mode | success rate when mode appears | mean grounding score in failed rows |
| --- | --- | --- | --- | --- | --- |
| evidence misinterpreted | 209 | 0.542857 | 350 | 0.402857 | 0.451171 |
| evidence disconnected from action | 204 | 0.52987 | 354 | 0.423729 | 0.480519 |
| evidence found but ignored | 12 | 0.031169 | 14 | 0.142857 | 0.029064 |
| evidence found too late | 12 | 0.031169 | 27 | 0.555556 | 0.029064 |
| evidence replaced by hallucinated reasoning | 1 | 0.002597 | 26 | 0.961538 | 0.25 |

## Interpretation

Most failed grounding is not absence of evidence. It is evidence attrition after recognition: evidence is misread, arrives too late to reshape the trajectory, or is never connected to concrete action. Hallucinated replacement is a smaller but important class: the run acts despite weak recognized evidence.
