# Mechanism Necessity

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Attack: remove grounding or commitment and ask whether success can still occur.

## Presence / Absence

| condition | rows | success rate | successful rows | failed rows |
| --- | --- | --- | --- | --- |
| grounded | 249 | 0.88755 | 221 | 28 |
| ungrounded | 669 | 0.466368 | 312 | 357 |
| committed | 83 | 0.891566 | 74 | 9 |
| uncommitted | 835 | 0.549701 | 459 | 376 |

## Removal Loss

| model | feature count | holdout R2 | holdout delta vs core | prospective R2 | prospective delta vs core | prospective Brier gain |
| --- | --- | --- | --- | --- | --- | --- |
| evidence only | 7 | 0.46012 | -0.181063 | 0.041296 | -0.038742 | 0.007507 |
| mechanism core | 16 | 0.641183 | 0.0 | 0.080038 | 0.0 | 0.014549 |
| remove grounding variables | 12 | 0.625139 | -0.016044 | 0.058987 | -0.021051 | 0.010723 |
| remove commitment variables | 11 | 0.597608 | -0.043575 | 0.07479 | -0.005248 | 0.013595 |
| grounding only over evidence | 11 | 0.597608 | -0.043575 | 0.07479 | -0.005248 | 0.013595 |
| commitment only over evidence | 12 | 0.625139 | -0.016044 | 0.058987 | -0.021051 | 0.010723 |
| full dynamic trajectory | 23 | 0.611615 | -0.029568 | 0.117627 | 0.037589 | 0.021382 |

## Necessity Verdict

Grounding is practically necessary but not logically necessary. Success without grounding exists, but the success rate is much lower and the ablation loses explanatory power.

Commitment is necessary as an outcome bottleneck in the loose execution sense, but `first_branch_collapse` is not a perfect necessity variable. Some successes occur without the measured commitment event because commitment can be implicit, late, or represented by convergence rather than the specific branch-collapse flag.
