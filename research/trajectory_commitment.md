# Trajectory Commitment

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

## Prefix Predictability

| execution prefix | feature count | holdout R2 | holdout Brier gain | prospective R2 | prospective Brier gain | holdout uncertainty p(1-p) | uncertainty collapse |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0% | 7 | 0.406068 | 0.090805 | 0.0 | -0.005365 | 0.147799 | 0.0 |
| 10% | 9 | 0.342405 | 0.076569 | 0.0 | -0.01362 | 0.154674 | -0.046518 |
| 25% | 13 | 0.423852 | 0.094782 | 0.005219 | 0.000949 | 0.154735 | -0.046928 |
| 50% | 17 | 0.632214 | 0.141375 | 0.109202 | 0.01985 | 0.088636 | 0.400294 |
| 75% | 21 | 0.613042 | 0.137088 | 0.039278 | 0.00714 | 0.095919 | 0.351017 |
| 90% | 24 | 0.624795 | 0.139716 | 0.099063 | 0.018007 | 0.096129 | 0.349597 |

## Determination

Outcome becomes materially predictable at `50%` under the robustness gate used here. Uncertainty does not collapse at the initial pre-run point; it collapses as retrieval/evidence signals are converted into grounded action and branch commitment.
