# Randomization Controls

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Grounding metrics, grounding scores, and warning fields were shuffled across rows with outcomes, K/rho/A1-A3, task family, model family, and benchmark left intact.

## Model Signal

| condition | holdout R2 | holdout AUC | R2 gain over baseline | max shuffled R2 |
| --- | --- | --- | --- | --- |
| baseline real | 0.416094 | 0.86094 | n/a | n/a |
| GI score real | 0.487146 | 0.919267 | 0.071052 | n/a |
| GI metrics real | 0.592381 | 0.945392 | 0.176287 | n/a |
| combined real | 0.591585 | 0.945392 | 0.175491 | n/a |
| combined shuffled mean | 0.410629 | 0.872673 | -0.005465 | 0.441072 |

## Warning Signal

| condition | warning lift | max shuffled lift | real-minus-shuffled mean |
| --- | --- | --- | --- |
| real strongest warning lift | 0.177753 | n/a | n/a |
| shuffled warning lift mean | 0.014756 | 0.03866 | 0.162997 |

## Determination

The result survives randomization only if real Grounding Integrity materially exceeds shuffled Grounding Integrity. Residual shuffled signal indicates that some apparent gain can be produced by baseline/corpus structure alone.
