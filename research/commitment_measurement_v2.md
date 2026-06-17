# Commitment Measurement V2

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Goal: improve branch commitment measurement without adding a new theory or primitive. V2 decomposes the old branch-collapse proxy into the requested observables.

## V2 Metrics

| measure | success mean | failure mean | success minus failure | operational reading |
| --- | --- | --- | --- | --- |
| first branch choice | 0.454034 | 0.072727 | 0.381306 | first non-exploring branch is grounded/converging/recovered |
| branch stability | 0.777361 | 0.960173 | -0.182812 | low switch rate across execution states |
| branch reversibility | 0.358349 | 0.545455 | -0.187106 | late repair or repeated branch switching remains possible |
| branch lock-in | 0.842402 | 0.981818 | -0.139417 | collapse/stable terminal state reached |
| premature commitment | 0.243902 | 0.353247 | -0.109344 | early choice before adequate grounding |
| false commitment | 0.093809 | 0.348052 | -0.254243 | locked branch fails or ends stuck |

## Measurement Upgrade Test

| model | holdout R2 | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- |
| old grounding + commitment | 0.641183 | 0.080038 | 0.014549 |
| v2 grounding + commitment | 0.615194 | 0.04689 | 0.008523 |
| v2 commitment over evidence | 0.491342 | 0 | -0.014312 |

## Determination

Better commitment measurement strengthens the mechanism diagnostically. The largest improvement is not raw timing; it is separating useful lock-in from premature and false commitment. The v2 metrics also explain why the previous branch-collapse flag was imperfect: commitment can be implicit, reversible, late, or wrong.
