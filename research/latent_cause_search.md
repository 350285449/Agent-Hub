# Latent Cause Search

Scope: Cloud-only aligned rows: 918. Excluded aligned rows: 173. Prior prospective cloud rows reconstructed: 67.

Attack: search for an existing latent execution process that explains both grounding and commitment. No new latent theory or primitive is introduced; this uses the already defined hidden execution states from trajectory clustering.

## Latent Replacement Test

| model | feature count | holdout R2 | prospective R2 | prospective Brier gain |
| --- | --- | --- | --- | --- |
| evidence baseline | 7 | 0.46012 | 0.041296 | 0.007507 |
| latent state only over evidence | 13 | 0.470363 | 0.0 | -0.000569 |
| compressed mechanism | 16 | 0.641183 | 0.080038 | 0.014549 |
| mechanism + latent state | 22 | 0.649671 | 0.01497 | 0.002721 |
| full trajectory | 23 | 0.611615 | 0.117627 | 0.021382 |

## Hidden States

| hidden state | rows | success rate | grounding rate | commitment rate | mean grounded-action ratio |
| --- | --- | --- | --- | --- | --- |
| H0 | 267 | 0.397004 | 0.0 | 0.0 | 0.097605 |
| H1 | 277 | 0.490975 | 0.0 | 0.0 | 0.25775 |
| H2 | 87 | 0.505747 | 0.0 | 0.0 | 0.076149 |
| H3 | 30 | 0.6 | 0.0 | 0.0 | 0.575738 |
| H4 | 257 | 0.891051 | 0.968872 | 0.322957 | 0.705136 |

## Determination

A deeper latent execution-quality process is plausible: hidden states jointly organize grounding, commitment, and success. But it does not replace the compressed mechanism cleanly. The latent state account is less interpretable, does not remove the need for grounding/action variables, and gains most force by re-expressing trajectory behavior already captured by grounding plus commitment.
